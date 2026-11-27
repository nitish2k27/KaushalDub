# 3. The computer-vision part: the step recogniser

**Job of this model:** given a how-to video and its skill (for example PerformCPR), say **which step happens at every moment**. For example: 0–31 s is background, 31–34 s is "check mouth", 35–44 s is "check breath", and so on.

In research terms this task is called **Temporal Action Segmentation (TAS)**. It means one label for every frame, not one label for the whole video.

Code: `ml/kaushaldub_model/kd_model.py`, `ml/kaushaldub_model/kd_metrics.py`.
Training notebook: `notebooks/kaushaldub_train.ipynb`, run on Kaggle with a T4 GPU.
Weights: `ml/kaushaldub_model/model.pt` (about 4 MB), plus `config.json`.

---

## 3.1 The big picture

```mermaid
flowchart LR
  V[Video] -->|ffmpeg 2 fps, 224x224| F[Frames T x 224 x 224 x 3]
  F -->|Frozen CLIP ViT-B/16 image encoder| X[Features T x 512]
  X --> S1[TCN stage 1: 6 dilated residual layers, 128 ch]
  S1 --> S2[TCN stage 2: 6 dilated residual layers, 128 ch]
  S2 --> P[1x1 projection to 512 + residual CLIP feature, L2 normalise]
  P --> H[Cosine head for this skill: similarity to each step vector x scale]
  H --> SM[Softmax with per-skill temperature]
  SM --> D[Decode: argmax, smooth <2 s blips, merge same labels]
  D --> O[Steps: label, start, end, confidence, low-conf flag]
```

In one sentence: **frozen CLIP looks at each frame, a temporal convolutional network (MS-TCN) looks at the frame sequence to understand order and context, and a cosine classifier, initialised from CLIP text embeddings of the step names, gives the step label for every frame.**

There are two parts:

| Part | Trainable? | Params | Role |
|---|---|---|---|
| **Backbone:** CLIP ViT-B/16 image encoder | **No (frozen)** | 86.2 M | "What is in this frame?" as a 512-number vector |
| **Temporal model:** MS-TCN with 2 stages | Yes | ≈1.0 M | "Given the frames before and after, which step is this?" |
| **Heads:** one cosine head per skill | Yes | 512 × classes | maps the embedding to step classes |

---

## 3.2 What is CLIP?

**CLIP** (Contrastive Language–Image Pre-training) is a model released by OpenAI in 2021 (Radford et al.).

- **Training data:** 400 million (image, caption) pairs from the internet.
- **Two encoders:** an **image encoder** and a **text encoder**, both of which output a 512-dimensional vector.
- **Contrastive training:** in a batch of N images and N captions, the model is trained so that each image's vector is close (high cosine similarity) to *its own* caption and far from the other N−1 captions. The loss is a symmetric cross-entropy over the N×N similarity matrix.
- **Result:** images and sentences live in **the same vector space**. A photo of someone pressing a chest lies near the text "press the chest of the patient". That property makes **zero-shot classification** possible: you compare an image with the text of every class and pick the closest.

**Why CLIP for us?**
1. It gives strong, general visual features, so we needed **no GPU-heavy fine-tuning**. We freeze it and train only about 1 M parameters.
2. Its **text encoder** lets us initialise each step class from the step's *name* (explained in §3.5). The untrained model is therefore already a zero-shot classifier, and new skills can be added from a few examples.
3. In our experiments it beat ImageNet ResNet-50 features by 4–6 macro-F1 points.

### CLIP ViT-B/16: the architecture inside

"ViT-B/16" means a **Vision Transformer, Base size, 16×16 patches**:

```
224x224x3 image
  -> cut into 14x14 = 196 patches of 16x16 pixels
  -> each patch flattened and linearly projected to 768-d, plus a learned position embedding
  -> a [CLS] token is added in front (197 tokens)
  -> 12 transformer encoder layers (12 attention heads, width 768, MLP 3072, LayerNorm, residuals)
  -> the [CLS] output goes through a final linear projection to 512-d
  -> L2-normalised, giving the frame feature x_t (512 numbers)
```

- **Self-attention:** every patch attends to every other patch, so the model sees global context (hand + phone + protector together).
- **Variant used:** `ViT-B-16-quickgelu` from the `open_clip` library with the original OpenAI weights. QuickGELU is the activation OpenAI used; it has to match the weights.
- **Input normalisation:** CLIP's own mean and std, `(0.481, 0.458, 0.408)` / `(0.269, 0.261, 0.276)`.

---

## 3.3 Why we need a temporal model

CLIP sees **one frame at a time**. A single frame of "hands on a chest" could be *checking breath* or *pressing the chest*. You can only tell from the frames around it: rhythmic movement, or what came before. Steps also come **in an order** and last several seconds. So we need a model over the **sequence** of frame features.

We compared two families:
- **RNN (BiLSTM):** reads the sequence step by step, forwards and backwards.
- **TCN (temporal convolution):** 1-D convolutions over time, with growing dilation. This is the one we used.

### MS-TCN (Multi-Stage Temporal Convolutional Network)

MS-TCN comes from Farha & Gall, CVPR 2019. Our version:

```
input  x: [T, 512] CLIP features (transposed to [512, T])
dropout 0.2
Stage 1:
  1x1 Conv1d 512 -> 128
  6 x DilatedResidualLayer, dilation = 1, 2, 4, 8, 16, 32:
        h = h + Dropout0.3( Conv1x1( ReLU( Conv3(dilation=d)(h) ) ) )
  1x1 projection 128 -> 512 (zero-initialised), + x (residual), L2 normalise -> z1
Stage 2:
  1x1 Conv1d 128 -> 128, then the same 6 dilated residual layers
  1x1 projection 128 -> 512 (zero-initialised), + x, L2 normalise -> z2
Each stage's z goes through the cosine head -> logits. Both stages get a loss; stage 2's output is used at inference.
```

- **Dilated convolution:** a kernel of size 3 that skips `d−1` frames. When the dilation doubles at each layer, the **receptive field grows exponentially**. Per stage it is 1 + 2·(1+2+4+8+16+32) = **127 frames ≈ 63 s** at 2 fps, and two stages see about 2 minutes. So every frame "sees" roughly a minute of context on each side.
- **Residual connections:** stable training and no vanishing gradients.
- **Multi-stage:** stage 2 *refines* stage 1's output and fixes flicker and over-segmentation.
- **Non-causal:** the convolution looks at past *and* future frames. That is fine because we process whole uploaded videos offline.
- **Zero-initialised projection + residual CLIP feature:** at the start of training the embedding *is* exactly the CLIP feature. Combined with text-initialised heads, this means the model starts as CLIP zero-shot and improves from there.

---

## 3.4 What is a BiLSTM? (baseline and ablation)

An **LSTM** (Long Short-Term Memory, Hochreiter & Schmidhuber, 1997) is a recurrent neural network with a memory cell and three gates:
- **forget gate f**: what to erase from memory;
- **input gate i**: what new information to write;
- **output gate o**: what to expose as the hidden state.

```
f_t = σ(W_f [h_{t-1}, x_t] + b_f)      i_t = σ(W_i [h_{t-1}, x_t] + b_i)
c~_t = tanh(W_c [h_{t-1}, x_t] + b_c)  c_t = f_t ⊙ c_{t-1} + i_t ⊙ c~_t
o_t = σ(W_o [h_{t-1}, x_t] + b_o)      h_t = o_t ⊙ tanh(c_t)
```

The gates solve the vanishing-gradient problem of plain RNNs, so the network can remember over long sequences.

A **Bidirectional LSTM** runs one LSTM forwards in time and one backwards, then concatenates their outputs. Each frame therefore knows both the past and the future.

Our BiLSTM baseline is **2 layers, 256 hidden units per direction (512 output), dropout 0.3, then a linear head per skill**. This is the classic "CNN + RNN" video model the professor suggested: a CNN extracts frame features and an RNN models time.

**TCN vs LSTM:**

| | TCN | BiLSTM |
|---|---|---|
| Computation | parallel over all frames (fast) | sequential (slower) |
| Context | fixed but large receptive field | in theory unlimited |
| Trainable params in our runs | 1.02 M | 3.17 M |
| Training time | 1.2 min | 5.8 min |
| Calibration (raw ECE) | **3.9 %** | 11.7 % |

---

## 3.5 Cosine heads and text initialisation (our main design idea)

A normal classifier computes `logit = W·z + b`. We use **cosine similarity × a learned scale**:

```
logit[t, c] = γ · cos(z_t, w_c) = γ · (z_t · w_c) / ||w_c||,    γ = exp(θ), θ learned (starts at log 15)
```

- There is **one weight matrix per skill** (for example PerformCPR has 7 rows: background plus 6 steps). The temporal network is **shared** across all skills, and only the head differs.
- **Initialisation from text:** each row `w_c` starts as the CLIP **text embedding** of the step name, averaged over three prompt templates:
  - `"{step}"`
  - `"a video of a person who is about to {step}"`
  - `"how to {step}: a step in a tutorial video"`

  Background uses prompts such as "a person talking to the camera", "the title screen or introduction of a tutorial video" and "a finished result being shown at the end of a video".

**Why this matters:**
1. **Zero-shot start:** before any training the model can already guess steps.
2. **Few-shot new skills:** to add a new skill we only need a new head. Its rows come from text embeddings, optionally blended with the mean embedding of a few labelled example frames (prototypes). We tested this on CookOmelet.
3. **Correction memory:** annotator-approved segments are blended into the class vectors at prediction time, with **no retraining** (§3.9).

---

## 3.6 Training phase

| Setting | Value |
|---|---|
| Hardware | Kaggle, NVIDIA **T4** GPU |
| Input | cached CLIP features (`.npy`), one video per batch (videos have different lengths) |
| Trained skills | 7 (3 target + 4 cooking); CookOmelet held out |
| Optimiser | **AdamW**, learning rate **1e-3**, weight decay **1e-4** |
| Gradient clipping | max norm **5** |
| Epochs | up to **60**, **early stopping** on validation macro-F1 (patience 12) |
| Dropout | 0.2 on the input, 0.3 inside each residual layer |
| Seed | 7 |
| Training time (main model) | **1.2 minutes**, because the CLIP features are pre-computed |

### Loss function

For **each stage** s (both stages are supervised, as in MS-TCN):

```
L = Σ_s [ CE_weighted(logits_s, y)  +  λ · SmoothingLoss(logits_s) ],    λ = 0.15

SmoothingLoss = mean over t of  min( (log p_t − log p_{t−1})², 16 )      (truncated MSE)
```

1. **Weighted cross-entropy:** a frame-wise classification loss. The class weight is `ω_c ∝ 1/√(n_c)` (normalised to mean 1). Background frames are very common and short steps are rare, so rare classes get more weight and the model does not just predict "background" everywhere.
2. **Truncated smoothing loss (T-MSE):** penalises big jumps in log-probability between neighbouring frames. This reduces **over-segmentation**, where labels flicker every few frames. It is truncated at 16 so that real step boundaries are not punished too hard.

### Calibration: temperature scaling

After training, for each skill we find a temperature T on the **validation** set that minimises negative log-likelihood. At inference we use `softmax(logits / T)`. Our temperatures are between 0.73 and 1.24, stored in `config.json`.

**Why calibrate?** We use the confidence number. A step with mean confidence **below 0.6** is flagged **low-confidence**: it gets a warning pill in the UI and its keyframe image is sent to the LLM. That only works if "0.6" really means about 60 % likely.

### Inference decoding (turning per-frame probabilities into steps)

1. `argmax` per frame gives the raw labels.
2. **Smoothing:** any segment shorter than **2 s** (4 frames) takes the label of its longer neighbour. This repeats until no short segments are left.
3. Consecutive frames with the same label become one segment. Each segment's confidence is the mean probability of its label over its frames.
4. Background segments are dropped, and the rest are numbered 1, 2, 3, ...
5. `merge_steps()` in the pipeline: same-label steps less than 3 s apart are joined, blips under 2 s are dropped, at most 12 steps are kept, and low confidence (< 0.6) is flagged.
6. If *every* frame came out as background (this happens on short clips), the backend **decodes again with background excluded** (`predict_forced`) and marks all steps low-confidence, so the trainer always gets something to review.

**Output per step:** `{idx, label, start, end, confidence, low_confidence, keyframe_s}`.

---

## 3.7 The five models we compared

All of them use the same splits, the same metrics and the same training recipe.

| # | Model | Frame features | Temporal model / head | Idea being tested |
|---|---|---|---|---|
| 1 | **CLIP zero-shot** | CLIP ViT-B/16 | none: cosine to the text embeddings of the step names | "Is text alone enough?" |
| 2 | **X-CLIP + linear** | X-CLIP B/32 *video* encoder (Microsoft): 8-frame windows (4 s), one per second; cross-frame attention | per-frame linear head | "Does a video-pretrained encoder help?" |
| 3 | **ResNet-50 + BiLSTM** | ResNet-50 trained on ImageNet (2048-d, CNN) | 2-layer BiLSTM, 256 per direction | the classic CNN-RNN baseline |
| 4 | **CLIP + BiLSTM** | CLIP ViT-B/16 | the same BiLSTM | ablation: swap the features, keep the RNN |
| 5 | **CLIP + MS-TCN (ours, deployed)** | CLIP ViT-B/16 | 2-stage TCN + cosine heads | proposed model |

**ResNet-50** is a 50-layer convolutional network with residual (skip) connections (He et al., 2016), trained on 1.28 M ImageNet images for 1000-class classification. Its last pooling layer gives a 2048-d vector per frame. It knows *objects*, but it was never trained to link images with language.

**X-CLIP** is CLIP extended to video. It adds cross-frame communication (attention across the 8 frames of a clip), so motion is captured inside the encoder itself.

---

## 3.8 Results: which model performed how well

### Metrics, explained simply

| Metric | What it measures | Analogy |
|---|---|---|
| **Frame accuracy** | % of frames labelled correctly | inflated by background, so not used alone |
| **Macro-F1** (main) | F1 per class over frames, averaged equally over classes | fair to rare steps |
| **F1@50** | a predicted *segment* counts as correct if it has the same label and IoU ≥ 50 % with a true segment | "did you find each step as a whole?" |
| **Edit score** | 100 × (1 − normalised Levenshtein distance) between the predicted and true **sequence of step labels** | "is the step order right?" (ignores timing) |
| **Boundary F1 @ 2 s** | predicted step start/end within ±2 s of a true one | "are the cut points right?" |
| **ECE** (expected calibration error) | gap between confidence and actual accuracy, 15 bins; lower is better | "when it says 80 %, is it right 80 % of the time?" |

### Main table (COIN test split, averaged over the 3 target skills)

| Model | Trainable / frozen params | **Macro-F1** | F1@50 | Edit | Boundary F1 | ECE raw → calibrated | Train time |
|---|---|---|---|---|---|---|---|
| CLIP zero-shot | 0 / 86.2 M | 16.7 | 7.4 | 29.8 | 28.6 | – → 16.3 % | 0 |
| X-CLIP + linear | 0.02 M / 133.4 M | 37.4 | 26.0 | 46.2 | **49.0** | 10.4 → 5.4 % | 0.6 min |
| ResNet-50 + BiLSTM | 6.32 M / 23.5 M | 37.9 | 30.9 | 44.3 | 39.7 | 15.6 → 5.5 % | 3.8 min |
| CLIP + BiLSTM | 3.17 M / 86.2 M | **44.3** | **34.9** | **47.8** | 42.3 | 11.7 → 5.9 % | 5.8 min |
| **CLIP + MS-TCN (ours)** | **1.02 M** / 86.2 M | 42.3 | 34.3 | 45.7 | 43.6 | **3.9** → 4.9 % | 1.2 min |

**How to read it (memorise this):**
1. **CLIP features matter most.** Both CLIP models beat ResNet-50 + BiLSTM by 4–6 points, because image–text pre-training gives better features.
2. **Zero-shot alone is poor (16.7).** Step names are not enough; supervised temporal training is required.
3. **X-CLIP has the best boundaries (49.0) but weak segments (26.0).** Its 4 s windows blur short steps.
4. **CLIP + BiLSTM is 2 points higher in macro-F1 than ours**, but F1@50 is almost equal (34.9 vs 34.3). Ours uses **3× fewer trainable parameters**, trains **5× faster**, and is the **only model that is well calibrated without temperature scaling** (3.9 % ECE).
5. **Why we deployed MS-TCN:** good accuracy, the best calibration (the 0.6 confidence threshold depends on it), small and fast, and **only the cosine-head design supports few-shot skills and the correction memory**.

### Per skill (macro-F1)

| Skill (test videos) | CLIP-TCN | CLIP-BiLSTM | ResNet-BiLSTM | X-CLIP |
|---|---|---|---|---|
| Screen protector (23) | 42.2 | 42.7 | 40.7 | 35.9 |
| CPR (17) | 37.5 | 39.4 | 31.8 | 32.3 |
| Car polishing (15) | 47.1 | 50.9 | 41.0 | 44.0 |
| Make pizza (20) | **62.2** | 52.1 | 58.2 | 58.8 |
| Rice cooker (14) | 53.5 | 60.7 | 41.8 | 53.2 |
| Mean over 5 skills | 48.5 | 49.1 | 42.7 | 44.8 |

- **CPR is the hardest skill.** Its steps are short and look alike: checking breath and checking pulse are both "hands near the head".
- **Cooking is easiest**, because the ingredients and tools are visually distinct.

### Data efficiency (how many videos does a skill need?)

| Training videos per skill | 5 | 10 | 20 | all |
|---|---|---|---|---|
| Macro-F1 | 25.5 | 29.6 | 33.6 | 43.9 |
| F1@50 | 10.1 | 21.0 | 28.1 | 32.9 |

More labelled data still helps a lot, and that is exactly what the annotator correction loop collects.

### Few-shot on an unseen skill (CookOmelet, never trained on)

| Method | K support videos | Macro-F1 |
|---|---|---|
| Text prototypes only | 0 | 15.7 |
| Prototypes (text + mean of support embeddings) | 1 | 18.6 |
| Prototypes | 5 | 25.6 |
| Prototypes | 10 | 25.8 |
| Head-only fine-tune | 5 | 28.5 |
| **Head-only fine-tune** | 10 | **31.0** |

So a new skill can be added with about 10 labelled videos, training just a new head in seconds.

### Real-world check

| Test | Result |
|---|---|
| CPR case-study video (120 s) | 5/5 steps, correct order (**edit 100**), macro-F1 79.3, F1@50 80.0 |
| 10 unseen videos on a laptop CPU | mean macro-F1 **41.0** (range 25.0–68.8), **1.11 s of CPU per second of video** |
| Live demo videos | pizza 68.8, screen protector 54.1, car 49.9, CPR 36.6 |

**Is 42 macro-F1 good?** For context, state-of-the-art TAS models on full COIN-like benchmarks, trained with heavy I3D features, typically score in the 40s–60s depending on the metric. COIN labels are coarse and we have only 14–23 test videos per skill. More importantly, the system is designed so that **a human trainer reviews every step** before anything is published.

---

## 3.9 Correction memory (human-in-the-loop active learning)

1. An annotator fixes a segment (changes its label or moves a boundary), and the trainer approves that change.
2. The CLIP-TCN **embeddings of the corrected frames** are stored in the `correction_memory` table for that skill and class.
3. Before the next prediction for the same skill, each class vector is blended with the mean of its stored corrections:

   ```
   w~_c = normalise( α · w_c + (1 − α) · mean(z_corrections_c) ),   α = max(0.5, 5 / (5 + n_c))
   ```

   With few corrections, the original vector dominates. With many, they get up to 50 % weight.
4. When **20 corrections are pending**, a **retrain** job fine-tunes the model with the same loss. The new version is **activated only if its test macro-F1 is not lower**.

This is **active learning with a human oracle, not reinforcement learning**. There is no reward signal and no policy, only human-verified labels.

---

## 3.10 Why not other options? (quick answers)

- **Fine-tune CLIP end to end?** That needs much more GPU memory and data (86 M parameters against our few hundred videos), with a big risk of overfitting. Frozen features train in about 1 minute.
- **ASFormer / transformers for time?** Possible future work. With our small data, the convolutional TCN is a strong, simple and well-understood baseline.
- **I3D / optical flow features?** They are heavy to compute on a CPU laptop. CLIP at 2 fps runs on the CPU at about 1.1× real time.
- **Why 2 fps?** Steps last several seconds, so 2 fps is enough to localise them to about 0.5 s and keeps CPU inference fast.
