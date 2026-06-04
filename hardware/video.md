# 視訊硬體設定（Phase 5）

> 攝影機、人臉追蹤、隱私。

---

## 這台 G713QC 的視訊

### 預期規格（待 Phase 5 驗證）

| 元件 | 預期 | 驗證方法 |
|------|------|----------|
| 內建視訊 | 720p 或 1080p | `cheese` 或 `ffplay /dev/video0` |
| 視訊裝置 | /dev/video0 | `ls /dev/video*` |
| 隱私蓋 | 無（多數筆電沒有） | 實體檢查 |
| 視訊燈號 | 自動（V4L2 標準） | 用中觀察 |

### 確認指令

```bash
# Linux
ls /dev/video*
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext
ffplay /dev/video0  # 預覽
```

---

## 用途對照

| 用途 | 最低需求 | 推薦 |
|------|----------|------|
| 人臉偵測 | 640x480 @ 15fps | 720p @ 30fps |
| 人臉追蹤 | 30fps for smoothness | 60fps |
| 表情判斷 | 較高解析度 | 1080p |
| 姿勢偵測 | 寬視角 | 廣角鏡頭 |
| 3D 重建 | 深度相機 | RealSense / Kinect |

v0 不用視訊。Phase 5 從「人臉追蹤」開始。

---

## 軟體堆疊

### v0/v1: 不啟用
攝影機不開，最省電、最隱私。

### Phase 5: 啟用 + 處理

```
應用: siro-runtime (Rust) → 透過 v4l2 syscalls 直接取 frame
      或 bridge (Python) → 透過 OpenCV / MediaPipe
  ↓
系統: V4L2 / libcamera
  ↓
硬體: 內建 UVC webcam
```

### 候選函式庫

| 函式庫 | 語言 | 用途 | Phase |
|--------|------|------|-------|
| OpenCV | C++/Python | 影像處理、人臉 | 5 |
| MediaPipe | C++/Python | 人臉 mesh、姿勢 | 5 |
| dlib | C++ | 人臉 landmark | 5+ |
| v4l2 (syscall) | C/Rust | 直接存取 | 5+ |

Phase 5 用 **OpenCV + MediaPipe**（最成熟）。

---

## 隱私設計

### 預設不開

- 攝影機平時完全關閉
- 開啟前需明確同意（kiosk 模式下跳出對話方塊）
- 開啟時螢幕顯示紅點（如果 Unity 支援）

### 本地處理

- 影像**不上傳**到任何雲端
- 處理完即丟 frame，不存影片
- 只存「事件」標籤（例：偵測到人臉 5 秒）

### 實體開關

如果硬體有視訊開關（華碩部分機型有），優先用實體的。
沒有就用「軟體開關」+ UI 提示。

---

## 攝影機角度

內建視訊通常在螢幕上方。
- 直立式螢幕：OK，能看到坐在前面的人
- 躺平式螢幕：看不到，要外接

Phase 5 評估。如果要外接 USB 視訊：
- 廣角 120°：推薦
- 可調支架：必備
- 帶腳架孔：加分

---

## V4L2 設定

### 列出支援的格式

```bash
v4l2-ctl -d /dev/video0 --list-formats-ext
```

### 設定常用解析度

```bash
v4l2-ctl -d /dev/video0 --set-fmt-video=width=1280,height=720,pixelformat=YUYV
v4l2-ctl -d /dev/video0 --set-parm=30  # 30fps
```

### udev 規則（固定裝置名）

`/etc/udev/rules.d/99-siro-camera.rules`：
```
KERNEL=="video[0-9]*", ATTRS{idVendor}=="xxxx", ATTRS{idProduct}=="xxxx", SYMLINK+="siro-camera"
```

之後 `/dev/siro-camera` 就指向 webcam（不管 hotplug 順序）。

---

## 視訊測試

### 基本測試

```bash
# 拍照
ffmpeg -f v4l2 -i /dev/video0 -frames:v 1 test.jpg

# 錄 10 秒
ffmpeg -f v4l2 -i /dev/video0 -t 10 test.mp4

# 預覽（需要 X11）
ffplay /dev/video0
```

### 進階測試（人臉偵測）

Python + OpenCV：

```python
import cv2
cap = cv2.VideoCapture(0)
face_cascade = cv2.CascadeClassifier('/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml')

while True:
    ret, frame = cap.read()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.1, 4)
    for (x, y, w, h) in faces:
        cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 0, 0), 2)
    cv2.imshow('Siro Camera Test', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
```

### 評估指標

- **人臉偵測率**：> 95% @ 1 米距離
- **誤報率**：< 5%
- **延遲**：frame 到結果 < 100ms
- **CPU 使用**：< 30% 單核

---

## 不在 Phase 5 範圍

- 多人同時偵測
- 情緒自動判斷（v2+）
- 視訊串流到外部
- 深度感知
- 手勢辨識（v2+）

---

## Phase 5 整合：人臉偵測 + 追蹤

### Python + OpenCV + MediaPipe 範例

```python
# hardware/face_detect_demo.py
import cv2
import mediapipe as mp
import time

# MediaPipe Face Detection
mp_face = mp.solutions.face_detection
mp_drawing = mp.solutions.drawing_utils
face_detection = mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.5)

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
cap.set(cv2.CAP_PROP_FPS, 30)

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    t0 = time.time()
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_detection.process(rgb)
    latency_ms = (time.time() - t0) * 1000

    if results.detections:
        for detection in results.detections:
            mp_drawing.draw_detection(frame, detection)

    # 顯示 FPS
    cv2.putText(frame, f"latency: {latency_ms:.0f}ms", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    cv2.imshow('SIRO Face Detection', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
```

跑起來：
```bash
pip install opencv-python mediapipe
python3 hardware/face_detect_demo.py
```

---

## 人臉追蹤 + Unity 連動（v1 規劃）

SIRO 的人臉追蹤不是「自動判斷表情」，是**判斷使用者有沒有在看 Mao**：
- 看到人 → Mao 表情可以「喚醒」
- 沒看到人 30 秒 → 待機動作
- 沒看到人 5 分鐘 → 螢幕保護

### 設計

```
[Camera] → [Face detection] → [Event: face_detected / face_lost]
  ↓
[siro-runtime subscribe] → [emit D-Bus signal]
  ↓
[Unity] → [EmotionDisplay 收 signal → 切待機 / 喚醒]
```

### Rust 端範例（siro-runtime）

```rust
// os/siro-runtime/src/camera.rs
use zbus::{dbus_interface, fdo::SignalContext};

struct CameraService;

#[dbus_interface(name = "com.siro.Camera")]
impl CameraService {
    /// 偵測到人臉
    #[dbus_interface(signal)]
    async fn face_detected(sig_ctx: &SignalContext<'_>, confidence: f32) -> zbus::Result<()>;

    /// 5 秒沒看到人
    #[dbus_interface(signal)]
    async fn face_lost(sig_ctx: &SignalContext<'_>) -> zbus::Result<()>;
}
```

Unity 端（Phase 5 實作）訂閱 D-Bus signal。

---

## 攝影機外接選項

| 選項 | 解析度 | FPS | 視角 | 推薦場景 |
|------|--------|-----|------|----------|
| **Logitech C920** | 1080p | 30 | 78° | ✅ 推薦 v1（Linux 友善、便宜）|
| Logitech C922 | 1080p | 60 | 78° | 🟡 高 FPS 需求 |
| Logitech Brio | 4K | 30 | 90° | ❌ 太貴、SIRO 用不到 4K |
| ELP 廣角 USB 攝影機 | 1080p | 30 | 120° | 🟡 廣角需求 |

### Logitech C920 設定

```bash
# 1. 確認裝置
v4l2-ctl --list-devices
# 預期：看到 "HD Pro Webcam C920"

# 2. 設固定解析度 + FPS
v4l2-ctl -d /dev/video0 --set-fmt-video=width=1280,height=720,pixelformat=YUYV
v4l2-ctl -d /dev/video0 --set-parm=30

# 3. udev 規則固定名稱
echo 'KERNEL=="video[0-9]*", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="082d", SYMLINK+="siro-camera"' | \
    sudo tee /etc/udev/rules.d/99-siro-camera.rules
sudo udevadm control --reload-rules

# 之後 /dev/siro-camera 固定指向 C920
```

---

## 視訊驗證 SOP（`hardware/verify-video.sh`）

```bash
#!/bin/bash
set -e

# 1. 確認攝影機
ls /dev/video* 2>&1
v4l2-ctl --list-devices

# 2. 拍照測試
ffmpeg -f v4l2 -i /dev/siro-camera -frames:v 1 test.jpg
file test.jpg  # 應該是 JPEG image

# 3. 解析度 + FPS 驗證
v4l2-ctl -d /dev/siro-camera --get-fmt-video
v4l2-ctl -d /dev/siro-camera --get-parm
# 預期：1280x720 YUYV @ 30fps

# 4. 人臉偵測（跑 Python 範例）
timeout 10 python3 hardware/face_detect_demo.py
# 手動確認有偵測到臉、latency < 100ms

# 5. CPU 使用
# （用 htop 看 30 秒）< 30% 單核

echo "ALL PASS"
```

---

## Phase 5 時程估算

| 項目 | 預估 | 風險 |
|------|------|------|
| Logitech C920 安裝 + V4L2 設定 | 0.5 天 | 低 |
| OpenCV + MediaPipe 整合（Python）| 1.5 天 | 中（MediaPipe model 載入慢）|
| 人臉追蹤 → D-Bus → Unity 端 | 2 天 | 高（siro-runtime Rust 端 + Unity C# 端兩邊接）|
| 攝影機角度調整 + udev 規則 | 0.5 天 | 低 |
| 隱私設計（紅點指示燈、UI 提示）| 1 天 | 中（要 Unity 端配合）|
| 驗證腳本 + 效能調校 | 1 天 | 低 |
| **總計** | **6.5 天** | — |
