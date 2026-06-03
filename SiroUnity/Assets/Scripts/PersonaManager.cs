// unity/Assets/Scripts/PersonaManager.cs
//
// v1+ 多角色架構：persona 切換的中央 controller
//
// 職責：
// - 啟動時 fetch persona 清單
// - 套用 persona 時：
//   1. 動態載入新 prefab（如果 path 不同）
//   2. 套 quirks 到 Live2DModelController
//   3. 通知 HermesBridgeClient 切換（之後送出的 chat 帶 personality=新 ID）
//
// 設計：每個 Unity scene 只需要一個 PersonaManager，掛在 root GameObject。

using System;
using System.Collections;
using UnityEngine;

namespace Siro
{
    public class PersonaManager : MonoBehaviour
    {
        [Header("References")]
        public PersonaApiClient apiClient;
        public HermesBridgeClient bridgeClient;
        public Live2DModelController modelController;
        public Transform characterAnchor;  // 角色 prefab 的 parent（動態載入時掛這下面）

        [Header("Initial Persona")]
        [Tooltip("啟動時預設載入哪個 persona，預設 siro-default")]
        public string defaultPersonaId = "siro-default";

        [Header("Debug")]
        public bool verboseLogging = true;

        // 目前套用的 persona
        private PersonaConfig _currentPersona;
        private GameObject _currentCharacterInstance;

        // 事件：persona 切換完成（給 UI 訂閱更新 dropdown）
        public event Action<PersonaConfig> OnPersonaChanged;

        private void Start()
        {
            if (apiClient == null)
            {
                Debug.LogError("[PersonaManager] 沒有指派 apiClient");
                return;
            }

            // 啟動時載入預設 persona
            ApplyPersona(defaultPersonaId);
        }

        // ==================== 公開 API ====================

        /// <summary>
        /// 切換到指定 persona。會：
        /// 1. 從 bridge fetch 完整 config
        /// 2. 比對 prefab_path，需要就動態載入
        /// 3. 套 quirks 到 model controller
        /// 4. 更新 HermesBridgeClient 的 activePersonality
        /// </summary>
        public void ApplyPersona(string personaId)
        {
            if (string.IsNullOrEmpty(personaId)) personaId = defaultPersonaId;

            if (verboseLogging) Debug.Log($"[PersonaManager] ApplyPersona: {personaId}");

            apiClient.FetchPersonaDetail(
                personaId,
                onSuccess: (config) => StartCoroutine(_ApplyConfig(config)),
                onError: (err) => Debug.LogError($"[PersonaManager] 載入 persona '{personaId}' 失敗: {err}")
            );
        }

        /// <summary>
        /// 拿目前 persona（給 UI 顯示用）
        /// </summary>
        public PersonaConfig GetCurrentPersona() => _currentPersona;

        // ==================== 內部 ====================

        private IEnumerator _ApplyConfig(PersonaConfig config)
        {
            if (config == null)
            {
                Debug.LogError("[PersonaManager] config 是 null");
                yield break;
            }

            _currentPersona = config;
            if (verboseLogging) Debug.Log($"[PersonaManager] 套用 persona: {config.name} (id={config.id}, prefab={config.prefabPath})");

            // 1. 動態載入新 prefab（如果需要）
            if (!string.IsNullOrEmpty(config.prefabPath))
            {
                yield return _EnsureCharacterPrefab(config);
            }
            else if (verboseLogging)
            {
                Debug.LogWarning($"[PersonaManager] persona '{config.id}' 沒指定 prefab_path，沿用場景內的 character");
            }

            // 2. 套 quirks 到 Live2DModelController
            if (modelController != null)
            {
                modelController.SetQuirks(
                    config.hideEyeOnExpressions,
                    config.eyeDrawableIndices
                );
            }

            // 3. 通知 bridge：之後送出的 chat 用這個 personality
            if (bridgeClient != null)
            {
                bridgeClient.SetActivePersonality(config.id);
            }

            // 4. 通知 UI
            OnPersonaChanged?.Invoke(config);
        }

        private IEnumerator _EnsureCharacterPrefab(PersonaConfig config)
        {
            // 簡易實作：從 Resources/ 載入 prefab
            // v1.1+ 換 Addressables
            if (verboseLogging) Debug.Log($"[PersonaManager] 載入 prefab: {config.prefabPath}");

            // Resources.Load 需要 path 不含副檔名
            // prefabPath 範例："Live2D/Cubism/Samples/Models/Mao/Mao"
            var loaded = Resources.Load<GameObject>(config.prefabPath);
            if (loaded == null)
            {
                Debug.LogError($"[PersonaManager] 找不到 prefab at Resources/{config.prefabPath}");
                yield break;
            }

            // 如果現有 instance 的 prefab 不一樣，就換掉
            if (_currentCharacterInstance != null &&
                _currentCharacterInstance.name.Replace("(Clone)", "").Trim() != loaded.name)
            {
                if (verboseLogging) Debug.Log($"[PersonaManager] 換角色: 銷毀舊的、instantiate 新的");
                Destroy(_currentCharacterInstance);
                _currentCharacterInstance = null;
            }

            if (_currentCharacterInstance == null && characterAnchor != null)
            {
                _currentCharacterInstance = Instantiate(loaded, characterAnchor);
                _currentCharacterInstance.name = loaded.name;

                // 重新拿 modelController 參考（新 prefab 才有 EmotionDisplay / Live2DModelController）
                if (modelController == null)
                {
                    modelController = _currentCharacterInstance.GetComponentInChildren<Live2DModelController>();
                }
            }

            yield return null;
        }
    }
}
