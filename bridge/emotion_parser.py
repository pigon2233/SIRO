"""
bridge/emotion_parser.py - 解析 Hermes 輸出中的情緒標籤

策略：
1. 優先：解析 `[emotion:xxx]` 標籤（Hermes 已被 prompt 要求輸出）
2. 備援：用簡單的關鍵字比對
3. 都失敗：回傳 neutral
"""

from __future__ import annotations

import json
import re
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from .models import Emotion, Live2DSignal

logger = logging.getLogger(__name__)


# 情緒標籤的 regex 模式
EMOTION_TAG_PATTERN = re.compile(r"\[emotion:(\w+)\]", re.IGNORECASE)

# Emoji + 雜項符號 regex（會從 clean_text 過濾掉）
# 動機：Unity TMP 的 Noto Sans TC 字型沒含 emoji glyph，顯示成 □。
# prompt 已經叫 LLM 不要用 emoji，這裡是後處理保險網。
# 範圍涵蓋：Emoticons / Pictographs / Symbols / Dingbats / Variation Selectors / ZWJ
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F000-\U0001FFFF"  # 廣義 emoji (Emoticons, Pictographs, Extended-A/B)
    "☀-➿"          # Misc Symbols + Dingbats (太陽、星、愛心、勾叉 等)
    "︀-️"          # Variation Selectors (emoji 變體選擇)
    "‍"                 # Zero Width Joiner (emoji 組合)
    "]+",
    flags=re.UNICODE,
)

# 備援用：中英文關鍵字（用於 agent_response，弱信號 fallback）
EMOTION_KEYWORDS = {
    Emotion.HAPPY: ["開心", "高興", "棒", "happy", "glad", "yay"],
    Emotion.JOYFUL: ["哈哈", "哈哈哈", "太好笑", "好笑", "lol", "lmao", "笑死"],
    Emotion.PROUD: ["驕傲", "得意", "我超棒", "很厲害", "厲害吧", "proud"],
    Emotion.SAD: ["難過", "傷心", "沮喪", "哭", "好難", "sad", "unfortunately", "sorry"],
    Emotion.ANGRY: ["生氣", "憤怒", "討厭", "氣", "angry", "mad", "annoyed"],
    Emotion.SURPRISED: ["驚訝", "吃驚", "哇", "真的嗎", "surprised", "wow", "omg", "really"],
    Emotion.THINKING: ["思考", "想想", "讓我", "應該", "thinking", "hmm", "let me think"],
    Emotion.EXCITED: ["興奮", "期待", "太棒了", "excited", "amazing", "awesome"],
}

# 強信號關鍵字（用於 user_input，明確情緒詞，會 override 弱 LLM 的 [emotion:xxx] tag）
# 設計動機：llama3.2:3b 對中文情緒判斷不穩，使用者明明說「難過」LLM 可能回 excited。
# 當使用者自己用了強情緒詞，相信使用者 > 相信小 LLM。
STRONG_USER_SIGNALS = {
    Emotion.SAD: ["難過", "傷心", "沮喪", "哭", "好慘", "好委屈", "好難受", "好悲傷", "心痛"],
    Emotion.ANGRY: ["生氣", "氣死", "氣到", "好氣", "超氣", "靠北", "幹", "可惡"],
    Emotion.SURPRISED: ["真的嗎", "天啊", "天哪", "我的天", "蛤", "什麼?!", "竟然"],
    Emotion.EXCITED: ["太棒了", "超棒", "讚啦", "太讚了", "yes!!", "yeah!!"],
    Emotion.THINKING: ["讓我想", "讓我思考", "我想想", "嗯..."],
    Emotion.JOYFUL: ["哈哈哈", "笑死", "太好笑", "lmao"],
    Emotion.PROUD: ["我考第一", "我贏了", "我超棒", "我超猛", "我超厲害"],
    # happy 留給 LLM 判斷（招呼語太多元，硬比關鍵字易誤判）
}


class EmotionParser:
    """情緒解析器"""

    def __init__(self, mapping_file: Optional[str] = None):
        """
        Args:
            mapping_file: emotion_mapping.json 的路徑
        """
        if mapping_file is None:
            mapping_file = Path(__file__).parent / "emotion_mapping.json"

        self.mapping_file = Path(mapping_file)
        self.mapping: Dict[str, Any] = self._load_mapping()

    def _load_mapping(self) -> Dict[str, Any]:
        """載入情緒映射表"""
        try:
            with open(self.mapping_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"找不到映射檔: {self.mapping_file}，使用預設")
            return {"emotion_map": {}}
        except json.JSONDecodeError as e:
            logger.error(f"映射檔 JSON 解析失敗: {e}")
            return {"emotion_map": {}}

    def parse(
        self,
        agent_response: str,
        user_input: Optional[str] = None,
    ) -> tuple[str, Emotion, float]:
        """
        解析 Agent 回應，抽出情緒與純文字。

        Args:
            agent_response: Hermes 的原始回應（可能含 [emotion:xxx] 標籤）
            user_input: 使用者輸入。若提供，會優先檢查強信號關鍵字
                       （明確情緒詞如「難過」、「生氣」），命中則 override LLM 判斷。
                       這是針對小 LLM 情緒判斷不穩的補強。

        Returns:
            (clean_text, emotion, intensity) 三元組
        """
        # 0. 強信號 override：使用者明確說的情緒詞 > 小 LLM 的猜測
        if user_input:
            strong = self._strong_user_signal(user_input)
            if strong is not None:
                clean_text = self._clean_for_display(agent_response)
                emotion_config = self.mapping.get("emotion_map", {}).get(strong.value, {})
                intensity = emotion_config.get("intensity", 0.7)
                logger.info(
                    f"強信號 override: user='{user_input[:30]}' → {strong.value} "
                    f"(忽略 LLM 的判斷)"
                )
                return clean_text, strong, intensity

        # 1. 找情緒標籤
        match = EMOTION_TAG_PATTERN.search(agent_response)
        if match:
            emotion_str = match.group(1).lower()
            try:
                emotion = Emotion(emotion_str)
            except ValueError:
                logger.warning(f"未知的情緒標籤: {emotion_str}，改用備援")
                emotion = self._fallback_keyword(agent_response)
        else:
            # 沒標籤，備援用關鍵字
            emotion = self._fallback_keyword(agent_response)

        # 2. 移除情緒標籤 + emoji，保留純文字
        clean_text = self._clean_for_display(agent_response)

        # 3. 從映射表拿強度
        emotion_config = self.mapping.get("emotion_map", {}).get(emotion.value, {})
        intensity = emotion_config.get("intensity", 0.7)

        return clean_text, emotion, intensity

    @staticmethod
    def _clean_for_display(raw: str) -> str:
        """
        準備要送到 Unity 顯示的文字：
        - 拿掉 [emotion:xxx] 標籤（純內部協議，使用者不需看到）
        - 拿掉 emoji（Noto Sans TC 沒含 emoji glyph，會顯示成 □）
        - trim
        """
        s = EMOTION_TAG_PATTERN.sub("", raw)
        s = EMOJI_PATTERN.sub("", s)
        # 連續空白壓成單一空白，避免 emoji 拿掉後留下兩個空白
        s = re.sub(r"[ \t]+", " ", s)
        return s.strip()

    def _strong_user_signal(self, user_input: str) -> Optional[Emotion]:
        """檢查使用者輸入是否含強信號關鍵字（明確情緒詞）"""
        text_lower = user_input.lower()
        for emotion, keywords in STRONG_USER_SIGNALS.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    return emotion
        return None

    def _fallback_keyword(self, text: str) -> Emotion:
        """備援：關鍵字比對"""
        text_lower = text.lower()
        scores: Dict[Emotion, int] = {e: 0 for e in EMOTION_KEYWORDS}

        for emotion, keywords in EMOTION_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    scores[emotion] += 1

        # 找最高分
        best = max(scores.items(), key=lambda x: x[1])
        if best[1] > 0:
            return best[0]

        return Emotion.NEUTRAL

    def to_live2d_signal(self, emotion: Emotion, intensity: float) -> Live2DSignal:
        """
        根據情緒與強度，產生 Live2D 動畫指令。

        Args:
            emotion: 偵測到的情緒
            intensity: 強度 (0-1)

        Returns:
            Live2DSignal: 給前端的動畫指令
        """
        config = self.mapping.get("emotion_map", {}).get(emotion.value, {})

        return Live2DSignal(
            expression_id=config.get("expression_id", "F01"),
            motion_group=config.get("motion_group"),
            motion_index=config.get("motion_index"),
            intensity=min(1.0, max(0.0, intensity)),
            duration_ms=config.get("duration_ms", 500),
        )
