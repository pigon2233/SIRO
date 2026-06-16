// unity/Assets/Scripts/PersonaConfig.cs
//
// v1+ 多角色架構：Persona runtime data 物件
//
// 對應 bridge 的 GET /personas/{id} 回應 schema (PersonaDetail)。
//
// 注意：Unity 的 JsonUtility 不支援 attribute rename 機制（[JsonProperty]），
// C# 欄位名要跟 JSON 欄位名**完全一致**。所以這邊刻意用 snake_case。
// 私有欄位、外人看不到，醜一點但功能正常。
//
// v1.1 fix：把 JSON 欄位統一改成 snake_case 對齊 Python Pydantic schema。

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Siro
{
    [Serializable]
    public class PersonaConfig
    {
        // ===== 基本識別 =====
        public string id;
        public string name;
        public string version;
        public string language;

        // ===== Model =====
        public string model_type;          // "cubism" 之類
        public string prefab_path;         // Resources/Addressable 路徑

        // ===== Quirks =====
        public string[] hide_eye_on_expressions = new string[0];
        public int[] eye_drawable_indices = new int[0];

        // ===== Emotion → Live2D signal（9 種）=====
        public Live2DExpressionConfig happy;
        public Live2DExpressionConfig joyful;
        public Live2DExpressionConfig proud;
        public Live2DExpressionConfig excited;
        public Live2DExpressionConfig sad;
        public Live2DExpressionConfig angry;
        public Live2DExpressionConfig surprised;
        public Live2DExpressionConfig thinking;
        public Live2DExpressionConfig neutral;

        // ===== Idle =====
        public string[] idle_motions = new string[0];
        public int[] idle_interval_seconds = new int[] { 15, 45 };

        // ===== Voice / TTS (Phase 1.5.1d) =====
        // bridge /personas/{id} response 內 voice 區段(對齊 persona yaml `voice:` 區段)
        // Unity 端要從這邊拿 TTS 設定送給 /tts/synthesize,不能 hard-code edge-tts
        public PersonaVoiceConfig voice;

        /// <summary>
        /// 拿某 emotion 對應的 Live2D signal config
        /// </summary>
        public Live2DExpressionConfig GetExpression(string emotionName)
        {
            if (string.IsNullOrEmpty(emotionName)) return null;
            switch (emotionName.ToLower())
            {
                case "happy": return happy;
                case "joyful": return joyful;
                case "proud": return proud;
                case "excited": return excited;
                case "sad": return sad;
                case "angry": return angry;
                case "surprised": return surprised;
                case "thinking": return thinking;
                case "neutral": return neutral;
                default: return null;
            }
        }

        /// <summary>
        /// 直接拿 emotion 對應的 expression_id（給 Live2DModelController.SetExpression 用）
        /// 找不到時 fallback 到 neutral
        /// </summary>
        public string GetExpressionId(string emotionName)
        {
            var expr = GetExpression(emotionName);
            if (expr != null && !string.IsNullOrEmpty(expr.expression_id))
            {
                return expr.expression_id;
            }
            // fallback 到 neutral
            if (neutral != null && !string.IsNullOrEmpty(neutral.expression_id))
            {
                return neutral.expression_id;
            }
            return null;
        }
    }

    [Serializable]
    public class Live2DExpressionConfig
    {
        public string expression_id;
        public string motion_group;
        public int motion_index;
        public float intensity;
        public int duration_ms;
    }

    /// <summary>
    /// TTS 聲線設定(Phase 1.5.1d)
    /// 對齊 persona yaml `voice:` 區段 — provider / voice_id / ref_audio / ref_text
    /// UnityTTSPlayer 會從這邊讀設定,而不是 hard-code fallback edge-tts
    /// </summary>
    [Serializable]
    public class PersonaVoiceConfig
    {
        public string provider;      // "edge-tts" | "piper" | "f5-tts" | "gpt-sovits"
        public string voice_id;      // 跨 provider 命名
        public string language;      // BCP-47 e.g. "zh-TW"
        public string gender;        // female | male
        public float speed;          // 0.5-2.0
        public float pitch;          // -10 ~ +10 semitones
        public string format;        // mp3 | opus | wav
        // F5-TTS 專用
        public string ref_audio;     // 6-30 秒 wav 路徑
        public string ref_text;      // ref_audio 對應文字
        public int nfe_step;         // F5-TTS 推論步數 16-64
        public float cfg_strength;   // F5-TTS CFG 1.0-3.0
        // GPT-SoVITS 專用
        public string refer_wav_path;
        public string prompt_text;
    }

    /// <summary>
    /// GET /personas 回應
    /// </summary>
    [Serializable]
    public class PersonaListResponse
    {
        public PersonaSummary[] personas;
        public string current_default;  // Python 回的是 snake_case
    }

    [Serializable]
    public class PersonaSummary
    {
        public string id;
        public string name;
        public string version;
        public string language;
        public string model_type;     // 對齊 Python
        public string prefab_path;    // 對齊 Python
    }
}
