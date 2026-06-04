// unity/Assets/Scripts/ScreenshotCapture.cs
//
// v0.x 截圖功能 — 點按鈕 / 觸發 task 把目前 Mao 畫面存成 PNG
//
// Phase 2 暫停項 #4 收尾。設計重點：
// - 用 RenderTexture + Texture2D.ReadPixels 抓目前 frame
// - 只截「指定 Camera 看到的範圍」（Mao 那個 camera、不是 UI camera）
// - 自動存到 Application.persistentDataPath / screenshots / <timestamp>.png
// - 可透過 SendTask "screenshot.capture" task 從 bridge 觸發（v1.5+ use case）
//
// 使用：
//   1. 場景加一個 ScreenshotCapture component
//   2. Inspector 設 targetCamera（Mao 那個 camera）
//   3. Inspector 設 outputResolution（預設 1920x1080）
//   4. 公開方法 CaptureNow() 立即截、或設快捷鍵 F12
//

using System;
using System.IO;
using UnityEngine;

namespace Siro
{
    public class ScreenshotCapture : MonoBehaviour
    {
        [Header("Capture Settings")]
        [Tooltip("要截的 Camera（Mao 渲染的 camera、不是 UI 的）")]
        public Camera targetCamera;

        [Tooltip("輸出解析度（寬）— 高的話 Mao 細節清楚、檔案也大")]
        public int outputWidth = 1920;

        [Tooltip("輸出解析度（高）")]
        public int outputHeight = 1080;

        [Header("Trigger")]
        [Tooltip("啟用 F12 快捷鍵截圖")]
        public bool enableF12Hotkey = true;

        [Tooltip("成功 / 失敗 log 開關")]
        public bool verboseLogging = true;

        [Header("v1.5+ Integration")]
        [Tooltip("HermesBridgeClient — 給 SendTask 觸發用、可不設")]
        public HermesBridgeClient bridge;

        private void Update()
        {
            if (enableF12Hotkey && Input.GetKeyDown(KeyCode.F12))
            {
                CaptureNow();
            }
        }

        private void Start()
        {
            // v1.5+：訂閱 SendTask result、讓 bridge 可以觸發截圖
            if (bridge != null)
            {
                bridge.OnTaskResult += OnTaskResult;
            }
        }

        private void OnDestroy()
        {
            if (bridge != null)
            {
                bridge.OnTaskResult -= OnTaskResult;
            }
        }

        private void OnTaskResult(BridgeTaskResult result)
        {
            // v1.5+：screenshot.capture task 觸發截圖
            // task_result.result 會有 { ok: true, path: "/path/to/file.png" } 或 { ok: false, error: "..." }
            // 目前 v1.2 階段、bridge 還沒 screenshot task、預留
        }

        /// <summary>
        /// 立即截圖。回傳存檔路徑（失敗回 null）。
        /// </summary>
        public string CaptureNow()
        {
            if (targetCamera == null)
            {
                Debug.LogError("[ScreenshotCapture] targetCamera 沒設");
                return null;
            }

            try
            {
                // 1. 開 RenderTexture（暫存 camera 渲染結果）
                RenderTexture rt = RenderTexture.GetTemporary(
                    outputWidth, outputHeight, 24, RenderTextureFormat.ARGB32
                );
                RenderTexture prevTarget = targetCamera.targetTexture;
                targetCamera.targetTexture = rt;
                targetCamera.Render();

                // 2. 讀回 CPU memory
                RenderTexture prevActive = RenderTexture.active;
                RenderTexture.active = rt;
                Texture2D tex = new Texture2D(outputWidth, outputHeight, TextureFormat.RGB24, false);
                tex.ReadPixels(new Rect(0, 0, outputWidth, outputHeight), 0, 0);
                tex.Apply();

                // 3. 還原 camera + RenderTexture state
                targetCamera.targetTexture = prevTarget;
                RenderTexture.active = prevActive;
                RenderTexture.ReleaseTemporary(rt);

                // 4. 編碼 PNG + 存檔
                byte[] png = tex.EncodeToPNG();
                UnityEngine.Object.Destroy(tex);

                // 5. 存到 persistentDataPath/screenshots/<timestamp>.png
                string dir = Path.Combine(Application.persistentDataPath, "screenshots");
                Directory.CreateDirectory(dir);
                string filename = $"siro_{DateTime.Now:yyyyMMdd_HHmmss}.png";
                string fullPath = Path.Combine(dir, filename);
                File.WriteAllBytes(fullPath, png);

                if (verboseLogging)
                {
                    Debug.Log(
                        $"[ScreenshotCapture] 截圖完成: {fullPath} ({png.Length / 1024} KB)"
                    );
                }
                return fullPath;
            }
            catch (Exception e)
            {
                Debug.LogError($"[ScreenshotCapture] 截圖失敗: {e}");
                return null;
            }
        }
    }
}
