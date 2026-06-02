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
