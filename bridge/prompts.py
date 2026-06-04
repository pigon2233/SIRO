"""
bridge/prompts.py - 角色 Persona 載入 + system prompt

設計（Phase 1.5+）：
- 角色性格從 bridge/personas/*.yaml 讀（資料與程式碼分離）
- 找不到指定 persona → fallback 到 siro-default
- 找不到 siro-default → fallback 到 hardcode 字串（最後保險網）

Persona schema 規範：docs/PERSONA.md
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ============ Persona 載入 ============

_PERSONAS_DIR = Path(__file__).parent / "personas"

# Module-level cache（單一進程內 persona 不會重 load）
_persona_cache: dict[str, dict[str, Any]] = {}


def _load_yaml(path: Path) -> Optional[dict[str, Any]]:
    """讀一個 YAML 檔。失敗回 None。"""
    try:
        import yaml
    except ImportError:
        logger.error("pyyaml 沒裝，pip install pyyaml")
        return None

    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            logger.error(f"{path} YAML 結構錯誤（root 不是 dict）")
            return None
        return data
    except Exception as e:
        logger.error(f"{path} YAML 解析失敗: {e}")
        return None


def load_persona(name: str = "siro-default") -> Optional[dict[str, Any]]:
    """
    載入一個 persona YAML。會 cache。

    Args:
        name: persona ID（檔名不含 .yaml）。"default" 會自動 alias 成 "siro-default"。

    Returns:
        dict 或 None（找不到）。
    """
    # alias 處理（向後相容舊呼叫）
    if name in ("default", "", None):
        name = "siro-default"

    if name in _persona_cache:
        return _persona_cache[name]

    path = _PERSONAS_DIR / f"{name}.yaml"
    data = _load_yaml(path)
    if data is None:
        return None
    _persona_cache[name] = data
    logger.info(f"✓ 載入 persona: {name} (v{data.get('version', '?')})")
    return data


def list_personas() -> list[dict[str, Any]]:
    """
    列出所有可用的 persona（讀 bridge/personas/ 目錄）

    v1 多角色用 — Unity persona selector 會 GET /personas 拿這清單。

    Returns:
        list of {id, name, version, language, model} dict
    """
    results = []
    if not _PERSONAS_DIR.exists():
        return results

    for path in _PERSONAS_DIR.glob("*.yaml"):
        # 跳過備份/暫存檔
        if path.name.startswith(".") or path.name.endswith(".local.yaml"):
            continue
        persona_id = path.stem
        persona = load_persona(persona_id)
        if persona is None:
            continue
        model = persona.get("model", {})
        results.append({
            "id": persona.get("id", persona_id),
            "name": persona.get("name", persona_id),
            "version": persona.get("version"),
            "language": persona.get("language"),
            "model_type": model.get("type"),
            "prefab_path": model.get("prefab_path"),
        })
    return results


# ============ Public API ============

# Hardcode fallback — 永遠不會走到，除非 personas/ 整個爛掉
_HARDCODE_FALLBACK_PROMPT = """你是一個溫暖、友善的陪伴型 AI 角色。
回應時請在開頭加 [emotion:happy] 之類的情緒標籤（happy/sad/angry/surprised/thinking/excited/joyful/proud/neutral）。
回應 1-3 句、繁體中文、不要用 emoji。"""


def get_personality(name: str = "default") -> str:
    """
    取得指定 persona 的 system prompt。

    Args:
        name: persona ID。"default" → siro-default。

    Returns:
        要送給 LLM 的 system prompt 字串。失敗會 fallback 到 hardcode。
    """
    persona = load_persona(name)
    if persona is None:
        logger.warning(f"找不到 persona '{name}'，用 hardcode fallback")
        return _HARDCODE_FALLBACK_PROMPT

    prompt = persona.get("personality", {}).get("system_prompt", "")
    if not prompt:
        logger.warning(f"persona '{name}' 沒有 personality.system_prompt，用 hardcode fallback")
        return _HARDCODE_FALLBACK_PROMPT
    return prompt


def get_fallback_response(category: str = "thinking", persona_name: str = "default") -> str:
    """
    取得降級回應（Hermes 死掉 / 網路斷時用）。

    Args:
        category: "thinking" / "error" / "disconnected"
        persona_name: 用哪個 persona 的 fallback pool

    Returns:
        隨機選一句，找不到回固定 fallback。
    """
    persona = load_persona(persona_name)
    if persona is not None:
        pool = persona.get("fallback_responses", {}).get(category, [])
        if pool:
            return random.choice(pool)

    # Hardcode fallback fallback（即使 persona 爛了也有東西回）
    hardcode = {
        "thinking": "嗯...",
        "error": "我有點不舒服，稍等",
        "disconnected": "我這邊好像連線怪怪的",
    }
    return hardcode.get(category, "...")


def get_persona_quirks(name: str = "default") -> dict[str, Any]:
    """
    取得 persona 的模型 quirks（hide_eye_on_expressions、eye_drawable_indices 等）。
    給 Unity 端做 runtime 客製用。
    """
    persona = load_persona(name)
    if persona is None:
        return {}
    return persona.get("model", {}).get("quirks", {})


def get_persona_expressions(name: str = "default") -> dict[str, Any]:
    """
    取得 persona 的 emotion → Live2D signal 映射（v0.2+ 取代 emotion_mapping.json）

    給 EmotionParser(persona_expressions=...) 用，讓 chat 回應的
    Live2DSignal 直接走 persona 設定的角色動作，不用再對照舊 JSON。

    Returns:
        dict 形如 {
            "happy": {"expression_id": "exp_01", "motion_group": "Idle", ...},
            "sad": {...},
            ...
        }，找不到 persona 回空 dict
    """
    persona = load_persona(name)
    if persona is None:
        return {}
    return persona.get("model", {}).get("expressions", {})


def get_persona_model_meta(name: str = "default") -> dict[str, Any]:
    """
    取得 persona 的模型基本資料（type、prefab_path）給 Unity 動態載入用。
    """
    persona = load_persona(name)
    if persona is None:
        return {}
    model = persona.get("model", {})
    return {
        "type": model.get("type"),
        "prefab_path": model.get("prefab_path"),
        "name": persona.get("name", name),
    }


def get_persona_visual(name: str = "default") -> dict[str, Any]:
    """
    取得 persona 的視覺設定檔（v0.3+ 視覺設定檔項目）

    給 Unity 啟動時套用 transform / canvas 設定用：
    - scale: 角色大小倍率
    - position: 錨點偏移（normalized -1~1）
    - anchor: 9-grid 錨點
    - brightness: 整體亮度
    - opacity: 透明度
    - mirror: 左右鏡像
    - z_order: Canvas sortOrder

    全部都有 default — 沒寫 YAML 也照跑，Unity 端不用判斷 None。

    Returns:
        dict 形如 {"scale":1.0,"position":{"x":0.0,"y":0.0},"anchor":"bottom-center",...}，
        找不到 persona 回預設值（跟 VisualSettings 對齊）
    """
    persona = load_persona(name)
    if persona is None:
        return {
            "scale": 1.0,
            "position": {"x": 0.0, "y": 0.0},
            "anchor": "bottom-center",
            "brightness": 1.0,
            "opacity": 1.0,
            "mirror": False,
            "z_order": 0,
        }
    visual = persona.get("model", {}).get("visual", {})
    # 合併 default：寫了什麼用什麼、沒寫用 default
    defaults = {
        "scale": 1.0,
        "position": {"x": 0.0, "y": 0.0},
        "anchor": "bottom-center",
        "brightness": 1.0,
        "opacity": 1.0,
        "mirror": False,
        "z_order": 0,
    }
    merged = {**defaults, **visual}
    # position 內部也要 merge（partial 寫 position 也要 work）
    if "position" in visual and isinstance(visual["position"], dict):
        merged["position"] = {**defaults["position"], **visual["position"]}
    return merged


# ============ 向後相容 ============

# 舊 code 用 PERSONALITIES dict 直接取 — Phase 2 後可移除
class _PersonalitiesShim:
    """模擬 dict 行為，但實際從 YAML 讀。

    語意跟 dict.get 一致：
    - key 存在且有 prompt → 回 prompt
    - key 缺 / 壞 → 回 user default（若有），否則回 hardcode fallback
    """
    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        persona = load_persona(name)
        if persona is not None:
            prompt = persona.get("personality", {}).get("system_prompt", "")
            if prompt:
                return prompt
        # 找不到 / 沒 prompt → 用 caller 給的 default，否則 hardcode
        if default is not None:
            return default
        return _HARDCODE_FALLBACK_PROMPT

    def __getitem__(self, name: str) -> str:
        return get_personality(name)


PERSONALITIES = _PersonalitiesShim()
