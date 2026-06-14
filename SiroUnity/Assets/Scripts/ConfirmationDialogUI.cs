// unity/Assets/Scripts/ConfirmationDialogUI.cs
//
// v1.5+ Computer control：SIRO 跑危險操作前需要 user 確認
// 收到 confirmation_request → 顯示 modal dialog
// 按「允許」/「拒絕」→ 推 confirmation_response 回 bridge
// 60s 沒按 → 自動拒絕（避免 SIRO 永遠等）
//
// 掛在 Canvas 上、需要：
// - 一個 GameObject panel 整個 dialog（dialogRoot, 預設隱藏）
// - 一個 Text / TMP_Text 顯示 description
// - 一個 Text / TMP_Text 顯示倒數計時（可選）
// - 兩個 Button：「允許」、「拒絕」
//
// 也可以多個 dialog queue 起來（如果 SIRO 連續發兩個 request）

using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using Newtonsoft.Json.Linq;

namespace Siro
{
    public class ConfirmationDialogUI : MonoBehaviour
    {
        [Header("UI References")]
        [Tooltip("整個 dialog 根物件（按按鈕時隱藏）")]
        public GameObject dialogRoot;

        [Tooltip("顯示 SIRO 想做什麼的文字")]
        public Text descriptionText;
        public TMP_Text tmpDescriptionText;

        [Tooltip("顯示 SIRO 想用哪個 tool（給 debug 用）")]
        public Text toolText;
        public TMP_Text tmpToolText;

        [Tooltip("顯示 SIRO 傳的 args（給 debug 用、JSON 格式）")]
        public Text argsText;
        public TMP_Text tmpArgsText;

        [Tooltip("顯示倒數計時（可選、不填就不顯示）")]
        public Text countdownText;
        public TMP_Text tmpCountdownText;

        [Tooltip("「允許」按鈕")]
        public Button allowButton;

        [Tooltip("「拒絕」按鈕")]
        public Button denyButton;

        [Header("Behavior")]
        [Tooltip("背景半透明遮罩（選填、給 modal 效果）")]
        public GameObject backdrop;

        private HermesBridgeClient _bridge;

        // 佇列：如果 SIRO 連續發多個 confirmation_request 排隊處理
        private Queue<BridgeConfirmationRequest> _queue = new Queue<BridgeConfirmationRequest>();
        private BridgeConfirmationRequest _current;

        // 倒數計時 coroutine
        private Coroutine _countdownCoroutine;
        private float _remainingSec;

        private void Start()
        {
            // 找 bridge
            _bridge = GetComponent<HermesBridgeClient>();
            if (_bridge == null) _bridge = GetComponentInParent<HermesBridgeClient>();
            if (_bridge == null) _bridge = FindFirstObjectByType<HermesBridgeClient>();

            if (_bridge == null)
            {
                Debug.LogError("[ConfirmationDialogUI] 找不到 HermesBridgeClient、component 不會工作");
                return;
            }

            // 訂閱 confirmation_request
            _bridge.OnBridgeConfirmationRequest += HandleConfirmationRequest;
            // 訂閱 confirmation_acked（如果 SIRO 在 timeout 內送了 response、我們可以知道 bridge 收到了）
            _bridge.OnBridgeConfirmationAcked += HandleConfirmationAcked;

            // 按鈕
            if (allowButton != null) allowButton.onClick.AddListener(OnAllowClicked);
            if (denyButton != null) denyButton.onClick.AddListener(OnDenyClicked);

            // 預設隱藏 dialog
            if (dialogRoot != null) dialogRoot.SetActive(false);
            if (backdrop != null) backdrop.SetActive(false);
        }

        private void OnDestroy()
        {
            if (_bridge != null)
            {
                _bridge.OnBridgeConfirmationRequest -= HandleConfirmationRequest;
                _bridge.OnBridgeConfirmationAcked -= HandleConfirmationAcked;
            }
            if (allowButton != null) allowButton.onClick.RemoveListener(OnAllowClicked);
            if (denyButton != null) denyButton.onClick.RemoveListener(OnDenyClicked);
        }

        // ============================================================
        // 收到 confirmation_request
        // ============================================================

        private void HandleConfirmationRequest(BridgeConfirmationRequest req)
        {
            // 排隊
            _queue.Enqueue(req);
            Debug.Log($"[ConfirmationDialogUI] 收到 confirmation_request id={req.confirmation_id} tool={req.tool}（queue={_queue.Count}）");

            // 如果現在沒顯示 dialog、立刻顯示
            if (_current == null)
            {
                ShowNext();
            }
        }

        private void ShowNext()
        {
            if (_queue.Count == 0)
            {
                HideDialog();
                _current = null;
                return;
            }

            _current = _queue.Dequeue();
            ShowDialog(_current);
        }

        private void ShowDialog(BridgeConfirmationRequest req)
        {
            // 顯示 dialog
            if (dialogRoot != null) dialogRoot.SetActive(true);
            if (backdrop != null) backdrop.SetActive(true);

            // 填文字
            SetText(descriptionText, tmpDescriptionText, req.description);

            // tool + args 給 debug 用
            string toolInfo = $"tool: {req.tool}";
            SetText(toolText, tmpToolText, toolInfo);

            string argsInfo = req.args != null ? req.args.ToString() : "{}";
            if (argsInfo.Length > 200) argsInfo = argsInfo.Substring(0, 200) + "...";
            SetText(argsText, tmpArgsText, $"args: {argsInfo}");

            // 倒數計時
            _remainingSec = req.timeout_sec;
            if (_countdownCoroutine != null) StopCoroutine(_countdownCoroutine);
            _countdownCoroutine = StartCoroutine(CountdownCoroutine());
        }

        private IEnumerator CountdownCoroutine()
        {
            while (_remainingSec > 0 && _current != null)
            {
                if (countdownText != null || tmpCountdownText != null)
                {
                    SetText(countdownText, tmpCountdownText,
                        $"{_remainingSec:F0}s 後自動拒絕");
                }
                yield return new WaitForSeconds(0.5f);
                _remainingSec -= 0.5f;
            }

            if (_current != null)
            {
                // Timeout！自動拒絕
                Debug.LogWarning($"[ConfirmationDialogUI] confirmation {_current.confirmation_id} timeout 自動拒絕");
                AutoReject();
            }
        }

        private void HideDialog()
        {
            if (dialogRoot != null) dialogRoot.SetActive(false);
            if (backdrop != null) backdrop.SetActive(false);
            if (_countdownCoroutine != null)
            {
                StopCoroutine(_countdownCoroutine);
                _countdownCoroutine = null;
            }
        }

        // ============================================================
        // 按鈕處理
        // ============================================================

        private async void OnAllowClicked()
        {
            if (_current == null) return;
            string id = _current.confirmation_id;
            Debug.Log($"[ConfirmationDialogUI] 允許 {id}");
            await _bridge.SendConfirmationResponse(id, approved: true);
            // 等 bridge 回 confirmation_acked 才關掉（HandleConfirmationAcked 處理）
        }

        private async void OnDenyClicked()
        {
            if (_current == null) return;
            string id = _current.confirmation_id;
            Debug.Log($"[ConfirmationDialogUI] 拒絕 {id}");
            await _bridge.SendConfirmationResponse(id, approved: false);
        }

        private void AutoReject()
        {
            if (_current == null) return;
            string id = _current.confirmation_id;
            Debug.Log($"[ConfirmationDialogUI] 自動拒絕（timeout）{id}");
            // 用 fire-and-forget 送（不能 await 這裡、會 block coroutine）
            _ = _bridge.SendConfirmationResponse(id, approved: false);
        }

        // ============================================================
        // 收到 confirmation_acked（bridge 確認收到 response）
        // ============================================================

        private void HandleConfirmationAcked(BridgeConfirmationAcked ack)
        {
            // 如果是當前 dialog 的 id → 關掉、顯示下一個
            if (_current != null && ack.confirmation_id == _current.confirmation_id)
            {
                Debug.Log($"[ConfirmationDialogUI] confirmation {ack.confirmation_id} 已 ack resolved={ack.resolved}");
                HideDialog();
                _current = null;
                // 顯示 queue 裡下一個
                ShowNext();
            }
        }

        // ============================================================
        // Helpers
        // ============================================================

        private void SetText(Text legacyText, TMP_Text tmpText, string value)
        {
            if (tmpText != null) tmpText.text = value;
            else if (legacyText != null) legacyText.text = value;
        }
    }
}
