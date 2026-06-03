// unity/Assets/Scripts/PersonaConfig.cs
//
// v1+ 多角色架構：Persona runtime data 物件
//
// 對應 bridge 的 GET /personas/{id} 回應 schema (PersonaDetail)。
// 用 [Serializable] 讓 Unity 也能反序列化 Inspector 設定的 ScriptableObject 備援。

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Siro
{
    [Serializable]
    public class PersonaConfig
    {
        public string id;
        public string name;
        public string version;
        public string language;

        [Header("Model")]
        public string modelType;          // "cubism" 之類
        public string prefabPath;         // Resources/Addressable 路徑

        [Header("Quirks")]
        public string[] hideEyeOnExpressions = new string[0];
        public int[] eyeDrawableIndices = new int[0];

        [Header("Emotion → Live2D signal")]
        public Live2DExpressionConfig happy;
        public Live2DExpressionConfig joyful;
        public Live2DExpressionConfig proud;
        public Live2DExpressionConfig excited;
        public Live2DExpressionConfig sad;
        public Live2DExpressionConfig angry;
        public Live2DExpressionConfig surprised;
        public Live2DExpressionConfig thinking;
        public Live2DExpressionConfig neutral;

        [Header("Idle")]
        public string[] idleMotions = new string[0];
        public int[] idleIntervalSeconds = new int[] { 15, 45 };

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
    /// GET /personas 回應
    /// </summary>
    [Serializable]
    public class PersonaListResponse
    {
        public PersonaSummary[] personas;
        public string current_default;
    }

    [Serializable]
    public class PersonaSummary
    {
        public string id;
        public string name;
        public string version;
        public string language;
        public string model_type;
        public string prefab_path;
    }
}
