"""
bridge/emotion_parser.py - 解析 Hermes 輸出中的情緒標籤

策略：
1. 優先：解析 `[emotion:xxx]` 標籤（Hermes 已被 prompt 要求輸出）
2. 備援：用 jieba 斷詞後比對關鍵字（避免 substring 假陽性）
3. 都失敗：回傳 neutral

注意：jieba 啟動時會建立 prefix dict（第一次 ~0.5s），
已用 jieba.dt.cache 做 module-level singleton 避免重複建。
"""

from __future__ import annotations

import json
import re
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from .models import Emotion, Live2DSignal

logger = logging.getLogger(__name__)

# jieba 延遲載入（避免 import 時就花 0.5s 建 dict）
_JIEBA = None


def _segment_chinese(text: str) -> list[str]:
    """中文斷詞。jieba 不可用時退回 char-level（無 word boundary）

    Returns:
        list of tokens。jieba 模式回 ["今天", "天氣", "還", "不錯"]，
        退回模式回 ["今", "天", "天", "氣", "還", "不", "錯"]（每字一個 token）
    """
    jieba = _get_jieba()
    if jieba is None:
        # 退回 char-level：把連續中文字拆成單字 token，
        # 非中文字（英數、標點、空格）保留原樣。
        # 注意這模式其實就退化成 substring matching，
        # 留著只是「jieba 沒裝也不會 crash」的 graceful degradation。
        tokens = []
        buf = ""
        for ch in text:
            if "一" <= ch <= "鿿":  # CJK Unified Ideographs
                if buf:
                    tokens.append(buf)
                    buf = ""
                tokens.append(ch)
            else:
                buf += ch
        if buf:
            tokens.append(buf)
        return tokens
    return list(jieba.cut(text))


# 常見情緒詞的 jieba 詞庫補強
# 動機：jieba 預設字典會把「生氣」切成「超生」+「氣」或「真的嗎」切成「真的」+「嗎」，
# 導致 EMOTION_KEYWORDS / STRONG_USER_SIGNALS 裡的 multi-char 詞匹配不到。
# 這裡把情緒關鍵字強制加進 jieba user dict，讓斷詞時不被切開。
_EMOTION_BOOST_WORDS = [
    # SAD
    "難過", "傷心", "沮喪", "好難受", "好悲傷", "心痛",
    # ANGRY
    "生氣", "憤怒", "討厭", "氣死", "可惡",
    # SURPRISED
    "真的嗎", "天啊", "天哪", "我的天",
    # EXCITED
    "太棒了", "超棒",
    # JOYFUL
    "哈哈哈", "太好笑",
    # PROUD
    "我超棒", "我超猛", "我超厲害",
    # THINKING
    "讓我想", "讓我思考", "我想想",
    # HAPPY
    "開心", "高興",
]


def _boost_jieba_dict(jieba):
    """把情緒關鍵字加到 jieba user dict（freq=高，確保不被切開）"""
    for word in _EMOTION_BOOST_WORDS:
        # freq=1_000_000 確保優先級最高
        jieba.add_word(word, freq=1_000_000, tag="emotion")


def _get_jieba():
    """取得 jieba 模組（延遲載入 + 自動加情緒詞到 user dict）"""
    global _JIEBA
    if _JIEBA is None:
        try:
            import jieba
            # jieba 預設 INFO log 太吵，壓成 WARNING
            jieba.setLogLevel("WARNING")
            # 把情緒詞加進 user dict，確保斷詞時不被切開
            _boost_jieba_dict(jieba)
            _JIEBA = jieba
        except ImportError:
            import sys
            logger.warning(
                "jieba 沒裝，_fallback_keyword 退回 substring 匹配（會有 false positive 如「天氣」→ angry）。"
                "pip install jieba 修正"
            )
            # v1.1+：印出實際 Python + sys.path 方便診斷「哪個 Python 沒裝」
            logger.warning(f"  Python: {sys.executable}")
            logger.warning(f"  sys.path[0:3]: {sys.path[:3]}")
            _JIEBA = False  # 標記為不可用，避免重試
    return _JIEBA if _JIEBA else None


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
    """情緒解析器

    兩個資料來源（優先序）：
    1. `persona_expressions` (v0.2+) — 從 persona YAML 的 model.expressions 傳入
       每個 emotion 對應 Live2DSignal 欄位 (expression_id, motion_group, ...)
    2. `mapping_file` (legacy) — 讀 emotion_mapping.json
       為了向後相容保留，沒有 persona 時才用

    換角色 = 換 persona → EmotionParser(persona_expressions=persona["model"]["expressions"])
    """

    def __init__(
        self,
        persona_expressions: Optional[Dict[str, Any]] = None,
        mapping_file: Optional[str] = None,
    ):
        """
        Args:
            persona_expressions: 直接傳入 emotion → Live2DSignal config 的 dict
                                 （從 persona["model"]["expressions"] 來）
            mapping_file: emotion_mapping.json 的路徑（legacy fallback）
        """
        self.persona_expressions = persona_expressions or {}
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
                emotion_config = self._get_emotion_config(strong.value)
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
            for try_emotion in (emotion_str, emotion_str[: len(emotion_str) // 2]):
                try:
                    emotion = Emotion(try_emotion)
                    break
                except ValueError:
                    continue
            else:
                logger.warning(f"未知的情緒標籤: {emotion_str}，改用備援")
                emotion = self._fallback_keyword(agent_response)
        else:
            # 沒標籤，備援用關鍵字
            emotion = self._fallback_keyword(agent_response)

        # 2. 移除情緒標籤 + emoji，保留純文字
        clean_text = self._clean_for_display(agent_response)

        # 3. 從映射表拿強度
        emotion_config = self._get_emotion_config(emotion.value)
        intensity = emotion_config.get("intensity", 0.7)

        return clean_text, emotion, intensity

    def _get_emotion_config(self, emotion_value: str) -> Dict[str, Any]:
        """拿某 emotion 對應的 Live2D signal config

        優先 persona_expressions（v0.2+），fallback 到 self.mapping（legacy）。
        """
        if self.persona_expressions:
            return self.persona_expressions.get(emotion_value, {})
        return self.mapping.get("emotion_map", {}).get(emotion_value, {})

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
        """檢查使用者輸入是否含強信號關鍵字（明確情緒詞）

        用 jieba 斷詞後比對 — 「天氣」斷成 [天, 氣]，不會誤觸「氣」(angry)。
        英文/數字 token 走原樣比對。
        """
        tokens = _segment_chinese(user_input)
        token_set = {t.lower() for t in tokens}
        token_str = " ".join(tokens).lower()  # 給 substring 比對 (英文關鍵字如 "lol")

        for emotion, keywords in STRONG_USER_SIGNALS.items():
            for kw in keywords:
                kw_lower = kw.lower()
                # 純英數關鍵字（"lol", "lmao", "yes!!"）走 substring
                # 中文關鍵字走 token set 比對（jieba 斷詞後的完整詞）
                if _is_chinese(kw):
                    if kw_lower in token_set:
                        return emotion
                else:
                    if kw_lower in token_str:
                        return emotion
        return None

    def _fallback_keyword(self, text: str) -> Emotion:
        """備援：關鍵字比對（jieba 斷詞版）

        之前用 substring 匹配會誤判（「天氣」含「氣」→ angry）。
        改用 jieba 斷詞後的 token set 比對：
        - 「天氣」斷成 [今天, 天氣, 還, 不錯] — token set 沒有「氣」，不誤判
        - 「生氣」斷成 [我, 好, 生氣] — token set 有「生氣」，正確命中 angry
        """
        tokens = _segment_chinese(text)
        token_set = {t.lower() for t in tokens}
        # 也保留 joined string 給英文/數字關鍵字用 substring
        token_str = " ".join(tokens).lower()

        scores: Dict[Emotion, int] = {e: 0 for e in EMOTION_KEYWORDS}

        for emotion, keywords in EMOTION_KEYWORDS.items():
            for kw in keywords:
                kw_lower = kw.lower()
                if _is_chinese(kw):
                    # 中文：token set 完全匹配（避免「天氣」誤觸「氣」）
                    if kw_lower in token_set:
                        scores[emotion] += 1
                else:
                    # 英數：substring 即可（"lol", "lmao", "thinking" 等）
                    if kw_lower in token_str:
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
        config = self._get_emotion_config(emotion.value)

        return Live2DSignal(
            expression_id=config.get("expression_id", "F01"),
            motion_group=config.get("motion_group"),
            motion_index=config.get("motion_index"),
            intensity=min(1.0, max(0.0, intensity)),
            duration_ms=config.get("duration_ms", 500),
        )


def _is_chinese(s: str) -> bool:
    """字串是否含中文字（CJK Unified Ideographs）

    用來分流匹配策略：
    - 中文關鍵字：jieba 斷詞後 token set 比對（避免 substring 假陽性）
    - 英數關鍵字：substring 比對（jieba 不會切英文）
    """
    return any("一" <= ch <= "鿿" for ch in s)
