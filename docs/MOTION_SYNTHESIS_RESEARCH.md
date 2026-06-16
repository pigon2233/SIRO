# Motion Synthesis Research — Live2D Mao 動作生成參考

> 給未來 Phase 7 / SIRO v2.0 做「Live2D MotionBricks」時的研究索引。
> 不直接用在 v1.0(3D humanoid 領域,跟 2D Live2D 圖層變形方法論不同),
> 但「latent generative + primitive 介面取代 hard-code 動作」的概念可借鏡。

---

## 為什麼開這個 doc

SIRO v1.0 Phase 4 「Live2D 豐富度」目前規劃是:
- **idle 動作多樣**:hard-code 3 個 motion(mtn_01/02/03)隨機切,避免單一 mtn_01 重複
- **hover 表情**:3 個區域 → 對應 3 個 emotion
- **滑鼠跟隨**:眼睛追滑鼠、body 微轉

這個方案 ship 沒問題,但根本限制是 **「動作是設計出來、不是生成出來」**:
- 要新動作要 MAO SDK 內建模組設計
- 不可能 infinite variety
- 風格切換要重新做 motion

3D character animation 領域已經走過這段路 — 從「手寫 animation graph」進化到「neural motion synthesis」。
如果 SIRO 想要 **「infinite Live2D 動作」+ 「風格切換零成本」**,需要類似路徑。

本 doc 整理 4 個關鍵研究,給未來做參考。

---

## 1. MotionBricks (NVIDIA GEAR Lab, SIGGRAPH 2026)

**URL**: https://nvlabs.github.io/motionbricks/
**GitHub**: https://github.com/NVlabs/GR00T-WholeBodyControl/tree/main/motionbricks (preview)
**完整版**: 約 1 個月後
**Training data**: [BONES-SEED](https://huggingface.co/datasets/bones-studio/seed) — 350k 真人動作捕捉

### 核心技術

- **Modular latent generative backbone** — 單一神經網路、2ms 延遲、15k FPS
- **Smart Primitives** 控制介面:
  - **Smart Locomotion** — 速度/方向/風格(殭屍、受傷、跳過、橫移)
  - **Smart Objects** — proxy keyframes 描述物件互動(撿劍、坐下、跳過長椅、跌倒)
- 覆蓋 350k 動作片段、零樣本遷移

### 為什麼重要

**第一個** 達到「plug-and-play 組合新行為」+「2ms 即時」+「350k 動作量級」的神經模型。
傳統做法要為每種任務手寫 animation graph、blending、IK、foot-locking、collision avoidance;
MotionBricks 把這些都換成神經推論,並用 latent 模組化設計支援跨任務組合。

### 跟 SIRO 的關係

- ❌ 不能直接用(3D humanoid joint trajectories,不是 2D Live2D 圖層變形)
- ✅ **概念借鏡**:
  - 「latent generative + primitive 介面」可套到 Live2D parameter space
  - Live2D parameter space(eye blink / mouth open / head angle / body)約 60-100 個,
    是 3D joint 數量(~30 個 joint × 6 DOF = 180)的 1/2~1/3
  - 用 motion capture(真人面試 + 3 軸頭部追蹤)+ 小 latent model 就有機會做

---

## 2. PFNN — Phase-Functioned Neural Networks (SIGGRAPH 2017)

**作者**: Daniel Holden、Taku Komura、Jun Saito
**論文**: [Phase-Functioned Neural Networks for Character Control](https://theorangeduck.com/page/publications)

### 核心技術

- 用 **NN 從 phase(步態週期相位)+ 控制訊號 → 下一個 pose**
- 訓練資料:1 個角色的 motion capture 序列(走、跑、跳)
- 優點:不再需要 blend tree、IK handle、foot locking — 全部 NN 學會
- 限制:要 1 個角色 1 個模型,跨角色 / 跨風格要重訓

### 跟 SIRO 的關係

- Live2D Mao 的 mtn_01~mtn_06(走路、轉身、idle...)是 discrete motion clip
- PFNN 概念可以擴展成:phase 函式 + 情緒參數 → 連續參數曲線
- 比 MotionBricks 簡單(單角色、單任務)、容易先 ship

---

## 3. NSM — Neural State Machine (SIGGRAPH 2021)

**作者**: Sebastian Starke, He Zhang, Taku Komura, Jun Saito
**論文**: [Neural State Machine for Character-Scene Interactions](https://theorangeduck.com/page/publications)

### 核心技術

- 把 character 控制拆成 **discrete states + neural transitions**
- 每個 state 有對應的 motion generator(可能是 PFNN、可能是一段 clip)
- 跨 state 切換由 NN 決定(不是 hard-code 條件判斷)
- 支援 character-object 互動(拿杯子、坐下、開門)

### 跟 SIRO 的關係

- Mao 有多個 emotion 跟 motion state
- 切換邏輯目前是「收到 emotion 訊息 → 切 expression + motion」
- NSM 概念可以擴展成:情緒 + 對話脈絡 + 滑鼠 hover → NN 決定最佳 state
- 不用再寫 if emotion == happy → mtn_01 / elif emotion == sad → mtn_05

---

## 4. AMP — Adversarial Motion Priors (SIGGRAPH 2021)

**作者**: Xue Bin Peng, Ze Ma, Pieter Abbeel, Sergey Levine, Angjoo Kanazawa
**論文**: [AMP: Adversarial Motion Priors for Stylized Physics-Based Character Control](https://xbpeng.github.io/projects/AMP/)

### 核心技術

- 用 **adversarial training** 學出 motion style
- 跟 RL 結合:讓 character 用 motion-capture 學會的風格完成 task
- 範例:學會走路的 reference → 訓練出「殭屍走」「企鵝走」「醉漢走」
- 一個 reference dataset 可以泛化到任何 task

### 跟 SIRO 的關係

- Mao 切換風格(嚴肅 vs 撒嬌)目前要 hard-code 多組 motion
- AMP 概念:給 1 組「嚴肅」motion + 1 組「撒嬌」motion → 自動產生風格混合
- 對標日本 VTuber 產業很需要(同一個角色不同直播有不同風格)

---

## 5. 其他相關研究

### Motion Matching (2016-)
- 動畫業界主流技術(《最後生還者 2》、《戰神》)
- 即時從大 database 找最像的下一段 motion
- 優點:不需要寫 blend tree,真實感高
- 缺點:database 大、搜尋成本高
- SIRO 應用:Live2D 可以做小 database(50-100 個 emotion 動作)→ 自動 match

### CALM — Conditional Adversarial Latent Model (NVIDIA 2022)
- 用 conditional GAN 學 latent motion code
- 可以 condition 在音樂、文字、參考 pose
- 跟 SIRO:可以用 LLM 輸出的情緒文字 condition 動作生成

### Learned Motion Matching (ML 2020)
- 把 motion matching 的 cost function 用 NN 學
- 搜尋更快、結果更自然

---

## 給 SIRO 的「Live2D MotionBricks」路徑建議

如果 Phase 7 真的要做,建議分 3 階段:

### Phase 7.1 — 資料蒐集(2 週)
- 用 webcam + 開源 mocap tool(Mediapipe / OpenPose / 3DiFACE)收 30 分鐘 Mao 風格動作
- 標註 emotion、動作類型(idle / 互動 / 滑鼠跟隨)、時間
- 存成 Live2D parameter trajectory 格式

### Phase 7.2 — 小 latent model(2 週)
- 用 NSM 概念:discrete state + neural transition
- 每個 state 訓練小 model(可以是 MLP、可以是 diffusion)
- 50 個 state → 50 個小 model → 5MB total,離線 inference

### Phase 7.3 — Smart Primitive 介面(1 週)
- LLM 輸出 emotion + intent → 對應到 state 機率分布
- 滑鼠位置 + hover 區域 → 對應到 state 機率分布
- 加權採樣選出下一個 state → 套到 Live2D

預估 **6-8 週**、2 個月,跟 v1.0 整體期程類似。

---

## 給 v1.0 的 interim 解法

在沒有 neural motion 之前,Phase 4 可以用:
1. **Random weighted motion switch** — 3 個 idle motion 按 emotion-weighted 採樣
2. **Emotion-driven parameter curves** — 用 animator curve 控制 Live2D 參數(嘴巴、眼睛、眉毛)
3. **Mouse follow with damping** — Lerp 滑鼠位置到 Live2D eyeLook、bodyAngle 參數

這些都是 Unity 內建功能、不需要訓練模型,但能讓 Mao 動作看起來「活」、不像 demo loop。

---

## 參考資源

### Paper / Project
- [MotionBricks](https://nvlabs.github.io/motionbricks/) — NVIDIA 2026
- [PFNN](https://theorangeduck.com/page/publications) — Holden et al. 2017
- [NSM](https://theorangeduck.com/page/publications) — Starke et al. 2021
- [AMP](https://xbpeng.github.io/projects/AMP/) — Peng et al. 2021
- [Learned Motion Matching](https://research.fb.com/publications/learned-motion-matching/) — Facebook 2020

### 開源工具
- [BONES-SEED](https://huggingface.co/datasets/bones-studio/seed) — 350k mocap dataset
- [GR00T-WholeBodyControl](https://github.com/NVlabs/GR00T-WholeBodyControl) — NVIDIA 開源 robot + 3D char 控制
- [Unity ML-Agents](https://unity.com/products/machine-learning-agents) — Unity 官方的 RL training
- [MediaPipe](https://google.github.io/mediapipe/) — Google 開源 mocap
- [XNect](https://github.com/facebookresearch/XNect) — Facebook 開源即時 mocap

### 對標日本 VTuber
- [Live2D Cubism SDK](https://www.live2d.com/en/sdk) — 現成工具
- [E-mote](https://emote.mtwo.co.jp/) — 另一個 2D 動畫 framework
- [VSeeFace](https://www.vseeface.icu/) — VTuber streaming 軟體

---

## 結論

| 技術 | 直接套用 | 概念借鏡 | SIRO v1.0 用得到 |
|---|---|---|---|
| MotionBricks | ❌ 3D only | ✅ latent + primitive | ❌ 太複雜 |
| PFNN | ❌ 3D | ✅ NN 取代 blend | ❌ 要 1 個角色 1 個 model |
| NSM | ❌ 3D | ✅ discrete state + NN | 🟡 邏輯可,但要 dataset |
| AMP | ❌ 3D + RL | ✅ style 從 ref 學 | 🟡 適合風格切換 |
| Motion Matching | 🟡 概念可 | ✅ 找最像 next pose | ✅ v1.0 簡化版 |

**SIRO v1.0 用 Unity 內建功能 + 小改 Live2D 參數動畫。**
**SIRO v2.0 / Phase 7 才考慮做 neural motion,從 small dataset + simple model 開始。**

---

**最後更新**: 2026-06-17
**作者**: Claude + jason
**相關**: [[siro-session-state]] Phase 4 Live2D 豐富度
