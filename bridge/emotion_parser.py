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

# 備援用：中英文關鍵字
EMOTION_KEYWORDS = {
    Emotion.HAPPY: ["開心", "高興", "哈哈", "😊", "太好了", "棒", "happy", "glad", "yay"],
    Emotion.SAD: ["難過", "傷心", "沮喪", "哭", "😢", "好難", "sad", "unfortunately", "sorry"],
    Emotion.ANGRY: ["生氣", "憤怒", "討厭", "😠", "氣", "angry", "mad", "annoyed"],
    Emotion.SURPRISED: ["驚訝", "吃驚", "哇", "😲", "真的嗎", "surprised", "wow", "omg", "really"],
    Emotion.THINKING: ["思考", "想想", "讓我", "🤔", "應該", "thinking", "hmm", "let me think"],
    Emotion.EXCITED: ["興奮", "期待", "😆", "太棒了", "excited", "amazing", "awesome"],
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

    def parse(self, agent_response: str) -> tuple[str, Emotion, float]:
        """
        解析 Agent 回應，抽出情緒與純文字。

        Args:
            agent_response: Hermes 的原始回應（可能含 [emotion:xxx] 標籤）

        Returns:
            (clean_text, emotion, intensity) 三元組
        """
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

        # 2. 移除情緒標籤，保留純文字
        clean_text = EMOTION_TAG_PATTERN.sub("", agent_response).strip()

        # 3. 從映射表拿強度
        emotion_config = self.mapping.get("emotion_map", {}).get(emotion.value, {})
        intensity = emotion_config.get("intensity", 0.7)

        return clean_text, emotion, intensity

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
