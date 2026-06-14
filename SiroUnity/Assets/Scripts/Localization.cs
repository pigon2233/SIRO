// unity/Assets/Scripts/Localization.cs
//
// v0.2 i18n 基礎：UI 字串集中管理
// v0.5+：auto-detect locale（systemLanguage + env LANG/LC_ALL）+ fallback chain
//
// 設計動機：之前 UI 字串散落各處（ChatInputUI、PersonaSelectorUI、
// Editor setup），換語言要改 N 個檔。集中到 Resources/i18n/zh-TW.json
// 之後加英文版只要建 en-US.json 切換。
//
// 用法：
//   1. Resources/i18n/zh-TW.json 集中所有 UI 字串
//   2. UI script 用 Localization.Get("ui.input.placeholder") 取
//   3. 支援 {0}、{1} placeholder 格式化：Localization.Get("key", arg1, arg2)
//   4. v0.5+ 用 reflection 統一處理（任何語言的 JSON 都吃）
//   5. v0.5+ Localization.AutoLoad() 用 Application.systemLanguage 自動選
//
// 支援的 locale（依 Resources/i18n/*.json 存在與否）：
//   zh-TW（預設） / en-US / ja-JP / ko-KR
// Fallback chain：要求 → 語系簡化（en-US → en）→ 預設 zh-TW

using System;
using System.Collections.Generic;
using System.Reflection;
using UnityEngine;

namespace Siro
{
    /// <summary>
    /// v0.5+ 維持 v0.2 的 typed field 設計、但用 reflection 動態取
    /// 任何語言的 JSON 只要 keys 對齊都能用、不用為每個 locale 寫一份 C# 類
    /// </summary>
    [Serializable]
    public class LocalizationData
    {
        // 對應 JSON 的 flat key-value（key 是 "ui_input_placeholder" 形式、點換底線）
        // Unity JsonUtility 吃 [Serializable] 公開欄位、不吃 Dictionary 所以這樣寫
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
        // v1.5+ confirmation dialog（2026-06-08）
        public string ui_confirm_title;
        public string ui_confirm_allow;
        public string ui_confirm_deny;
        public string ui_confirm_timeout_msg;
        public string ui_confirm_queued;
    }

    public static class Localization
    {
        public const string DEFAULT_LANG = "zh-TW";
        private const string RESOURCE_PATH = "i18n/";

        private static LocalizationData _current;
        private static string _currentLang = DEFAULT_LANG;

        /// <summary>
        /// 載入指定語言的 i18n 檔（從 Resources/i18n/{lang}.json）
        /// 找不到時回 false、呼叫端可以走 fallback chain
        /// </summary>
        public static bool Load(string lang)
        {
            var asset = Resources.Load<TextAsset>(RESOURCE_PATH + lang);
            if (asset == null)
            {
                Debug.LogWarning($"[Localization] 找不到 {RESOURCE_PATH}{lang}.json");
                return false;
            }
            try
            {
                _current = JsonUtility.FromJson<LocalizationData>(asset.text);
                _currentLang = lang;
                if (_current == null)
                {
                    Debug.LogError($"[Localization] 解析 {lang}.json 失敗：回傳 null");
                    return false;
                }
                Debug.Log($"[Localization] 載入 {lang} OK");
                return true;
            }
            catch (Exception e)
            {
                Debug.LogError($"[Localization] 解析 {lang}.json 失敗: {e.Message}");
                _current = null;
                return false;
            }
        }

        /// <summary>
        /// 載入帶 fallback chain（v0.5+）：
        /// 例：要求 "en-GB" → 試 en-GB → en → zh-TW
        /// </summary>
        public static bool LoadWithFallback(string preferred)
        {
            if (string.IsNullOrEmpty(preferred)) preferred = DEFAULT_LANG;
            var chain = new List<string> { preferred };
            if (preferred.Contains("-"))
            {
                chain.Add(preferred.Split('-')[0]);
            }
            if (!chain.Contains(DEFAULT_LANG))
            {
                chain.Add(DEFAULT_LANG);
            }
            foreach (var lang in chain)
            {
                if (Load(lang))
                {
                    return true;
                }
            }
            Debug.LogError($"[Localization] fallback chain 全部失敗：{string.Join(" → ", chain)}");
            return false;
        }

        /// <summary>
        /// v0.5+ 自動偵測 locale
        /// 順序：env var LANG/LC_ALL → Application.systemLanguage → 預設 zh-TW
        /// Linux/macOS/Windows 都能用
        /// </summary>
        public static bool AutoLoad()
        {
            string preferred = null;

            // 1. 環境變數（給 LANG / LC_ALL 用、Linux kiosk 模式 + 容器常見）
            string envLang = Environment.GetEnvironmentVariable("LC_ALL")
                          ?? Environment.GetEnvironmentVariable("LANG")
                          ?? Environment.GetEnvironmentVariable("LANGUAGE");
            if (!string.IsNullOrEmpty(envLang))
            {
                preferred = NormalizeLocale(envLang);
            }

            // 2. Unity 系統語言 fallback
            if (string.IsNullOrEmpty(preferred))
            {
                preferred = MapSystemLanguageToLocale(Application.systemLanguage);
            }

            Debug.Log($"[Localization] AutoLoad: system={Application.systemLanguage}, preferred={preferred}");
            return LoadWithFallback(preferred);
        }

        private static string MapSystemLanguageToLocale(SystemLanguage sl)
        {
            switch (sl)
            {
                case SystemLanguage.ChineseTraditional: return "zh-TW";
                case SystemLanguage.ChineseSimplified: return "zh-CN";
                case SystemLanguage.English: return "en-US";
                case SystemLanguage.Japanese: return "ja-JP";
                case SystemLanguage.Korean: return "ko-KR";
                case SystemLanguage.French: return "fr-FR";
                case SystemLanguage.German: return "de-DE";
                case SystemLanguage.Spanish: return "es-ES";
                case SystemLanguage.Portuguese: return "pt-PT";
                default: return DEFAULT_LANG;
            }
        }

        private static string NormalizeLocale(string raw)
        {
            if (string.IsNullOrEmpty(raw)) return null;
            // LANG=zh_TW.UTF-8 → zh_TW
            int dot = raw.IndexOf('.');
            if (dot > 0) raw = raw.Substring(0, dot);
            // zh_TW → zh-TW
            return raw.Replace('_', '-');
        }

        /// <summary>
        /// 自動載入（v0.2 寫法、保留向後相容）
        /// </summary>
        private static void EnsureLoaded()
        {
            if (_current == null)
            {
                LoadWithFallback(DEFAULT_LANG);
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
                BindingFlags.Public | BindingFlags.Instance);
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
                catch { return value; }
            }
            return value;
        }

        public static string CurrentLang => _currentLang;

        /// <summary>
        /// 切換語言（v0.5+ UI 給使用者手動切）
        /// </summary>
        public static bool SetLang(string lang)
        {
            return LoadWithFallback(lang);
        }
    }
}
