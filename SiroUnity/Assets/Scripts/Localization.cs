// unity/Assets/Scripts/Localization.cs
//
// v0.2 i18n 基礎：UI 字串集中管理
//
// 設計動機：之前 UI 字串散落各處（ChatInputUI、PersonaSelectorUI、
// Editor setup），換語言要改 N 個檔。集中到 Resources/i18n/zh-TW.json
// 之後加英文版只要建 zh-CN.json、en-US.json 切換。
//
// 用法：
//   1. Resources/i18n/zh-TW.json 集中所有 UI 字串
//   2. UI script 用 Localization.Get("ui.input.placeholder") 取
//   3. 支援 {0}、{1} placeholder 格式化：Localization.Get("key", arg1, arg2)
//
// 之後 v1 多語言切換：Localization.Load("en-US") 切換

using System;
using UnityEngine;

namespace Siro
{
    [Serializable]
    public class LocalizationData
    {
        // 對應 JSON 的 flat key-value
        public string ui_input_placeholder;
        public string ui_connect_waiting;
        public string ui_connect_disconnected;
        public string ui_connect_connected;
        public string ui_connect_reconnecting;
        public string ui_connect_reconnect_attempt;
        public string ui_send_thinking;
        public string ui_send_error_prefix;
        public string ui_send_unknown_error;
        public string ui_persona_loading;
        public string ui_persona_role;
        public string ui_persona_dropdown_loading;
    }

    public static class Localization
    {
        private const string DEFAULT_LANG = "zh-TW";
        private const string RESOURCE_PATH = "i18n/";

        private static LocalizationData _current;
        private static string _currentLang = DEFAULT_LANG;

        /// <summary>
        /// 載入指定語言的 i18n 檔（從 Resources/i18n/{lang}.json）
        /// </summary>
        public static bool Load(string lang = DEFAULT_LANG)
        {
            _currentLang = lang;
            var asset = Resources.Load<TextAsset>(RESOURCE_PATH + lang);
            if (asset == null)
            {
                Debug.LogError($"[Localization] 找不到 Resources/{RESOURCE_PATH}{lang}.json");
                return false;
            }
            try
            {
                _current = JsonUtility.FromJson<LocalizationData>(asset.text);
                Debug.Log($"[Localization] 載入 {lang} ({_current?.GetType().Name})");
                return _current != null;
            }
            catch (Exception e)
            {
                Debug.LogError($"[Localization] 解析 {lang}.json 失敗: {e.Message}");
                _current = null;
                return false;
            }
        }

        /// <summary>
        /// 自動載入（v0.2 用：第一次 Get 時 lazy load）
        /// </summary>
        private static void EnsureLoaded()
        {
            if (_current == null)
            {
                Load(DEFAULT_LANG);
            }
        }

        /// <summary>
        /// 拿 UI 字串。支援 {0}、{1} placeholder 格式化。
        /// 找不到 key 會回 "[missing:key]" 不會 crash，方便開發期除錯。
        /// </summary>
        public static string Get(string key, params object[] args)
        {
            EnsureLoaded();
            if (_current == null) return $"[missing:{key}]";

            // 用 reflection 拿對應的 public field（key 是 "ui.input.placeholder" → field "ui_input_placeholder"）
            string fieldName = key.Replace('.', '_');
            var field = typeof(LocalizationData).GetField(fieldName,
                System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance);
            if (field == null)
            {
                Debug.LogWarning($"[Localization] key '{key}' 找不到（field '{fieldName}'）");
                return $"[missing:{key}]";
            }

            var value = field.GetValue(_current) as string;
            if (string.IsNullOrEmpty(value))
            {
                return $"[missing:{key}]";
            }

            if (args != null && args.Length > 0)
            {
                try { return string.Format(value, args); }
                catch { return value; }  // format 失敗回原 string
            }
            return value;
        }

        public static string CurrentLang => _currentLang;
    }
}
