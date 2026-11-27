# 1. KaushalDub: the whole project, end to end

> **Kaushal** (कौशल) means *skill*. **KaushalDub** dubs skill videos.

## 1.1 The problem

- India's vocational training (Skill India, ITIs, NGOs) relies more and more on short **how-to videos**: CPR, fitting a screen protector, polishing a car, cooking.
- Most free tutorials are in **English**, but many trainees learn best in **Hindi or Kannada**.
- Re-recording every video in every language is slow and expensive.
- A plain "translate the audio" approach fails when the instructor barely speaks, or the audio is only music. That is common in how-to videos.

## 1.2 Our idea, in one line

> **First detect the steps visually, then narrate each step in the learner's language.**

Procedural videos have structure: steps happen in a fixed order and each step occupies a time interval. KaushalDub uses **computer vision** to find those steps. An **LLM** writes a short instruction for each step, grounded in what the instructor said. **Indic speech models** then translate and voice it, placed exactly over the matching action.

This gives three advantages:
1. It works **even without speech**, because the vision model defines the timeline.
2. The narration is **aligned with the action on screen**.
3. The trainer reviews a **small set of sentences** instead of a whole transcript.

## 1.3 What the user gets from one upload

| Output | Example |
|---|---|
| Numbered steps with times | 1. Knead the dough (12–31 s) · 2. Unroll the dough (33–58 s) · ... |
| Editable text per step | title, instruction, narration |
| Dubbed videos | `dubbed_hi.mp4`, `dubbed_kn.mp4` (Hindi and Kannada narration over the original at 15 % volume) |
| Captions | WebVTT files per language |
| Quiz | 3 multiple-choice questions, also translated |

## 1.4 The three roles (all sign in with Google)

| Role | What they do |
|---|---|
| **Trainer** | uploads, picks the skill and languages, **reviews and edits** steps, narration and quiz, approves, gets the dubs, publishes; handles learner reports and approves annotator corrections; manages API keys and plan |
| **Learner** | searches the library, watches in their language with a clickable step list and captions, takes quizzes, sees progress, **reports problems** at a timestamp |
| **Annotator** | corrects step labels and boundaries on clips (low-confidence first), with split, merge, relabel, accept and mark unclear; submits to the trainer |

## 1.5 Technology map: the "multimodal" course module

| Modality | Model / tool | Role in KaushalDub |
|---|---|---|
| **Vision** | CLIP ViT-B/16 (frozen) + MS-TCN (trained by us on COIN) | finds the steps and their times |
| **Speech → text** | Sarvam Speech-to-Text (Whisper or AI4Bharat IndicConformer locally) | transcript with word times, language detection |
| **Language (LLM)** | Gemini Flash → Groq GPT-OSS-120B → template | grounded step text and quiz |
| **Translation** | Sarvam Translate (or AI4Bharat IndicTrans2) | English → Hindi, Kannada |
| **Text → speech** | Sarvam Bulbul v3 (or AI4Bharat Indic Parler-TTS) | narration voice |
| **Media** | ffmpeg | split audio and frames, speed-up, mix, mux, captions |

## 1.6 The pipeline in 7 stages

```mermaid
flowchart LR
  U[Upload] --> S1[1 Extract audio + frames]
  S1 --> S2[2 Speech to text]
  S2 --> S3[3 Step detection: CLIP + MS-TCN]
  S3 --> S4[4 LLM: step text + quiz]
  S4 --> RV{{Trainer review + approve}}
  RV --> S5[5 Translate hi, kn]
  S5 --> S6[6 TTS voice]
  S6 --> S7[7 Place clips, mix, VTT, mux]
  S7 --> P[Publish to library]
```

Stages 1–4 run straight after the upload. Stages 5–7 run **only after a human approves**. Details: [04_SYSTEM_FLOW.md](04_SYSTEM_FLOW.md).

## 1.7 Extra features beyond the basic pipeline

1. **Learner reports (tickets).** A learner pauses the video and reports a problem; the timestamp, step, language and category (Wrong step, Wrong translation, Out of sync, Unclear, Unsafe, Other) are captured. The trainer jumps to that moment, edits the step text in that language, **re-voices just that step**, replies and closes the report.
2. **Annotator corrections → trainer approval → model learning.** The trainer compares two timelines (model vs annotator) and approves changes one by one. Approved changes:
   - update the video;
   - go into the **correction memory**, so the next video of the same skill improves immediately;
   - queue a **retrain** at 20 corrections, activated only if the score does not drop.

   This is *human-in-the-loop active learning*, not reinforcement learning.
3. **Plans and API keys.**
   - **Free trial:** 5 videos on the platform keys, enforced on the server.
   - **Bring your own keys:** Sarvam plus Gemini or Groq, **encrypted** with Fernet, with a test button for each key.
   - **Free local models:** AI4Bharat models on a GPU worker.
   - **Pro:** shown as "coming soon".
4. **Out-of-credit handling.**
   - HTTP 402 means out of credits: no retry, fall back to the next provider.
   - HTTP 429 means rate limited: retry with back-off.
   - If no provider is left, the job pauses as `needs_credits` with a clear message.
   - A monthly platform budget (`PLATFORM_BUDGET_INR`) stops platform-key jobs when it is reached.
5. **Two narration styles.** **Step narration** (short line per step, about ₹4) or **Full speech translation** (every sentence translated, original at 5 %, about ₹10–20).
6. **Cost tracking.** Every job records its estimated rupee cost per provider.

## 1.8 Key numbers to remember

| What | Number |
|---|---|
| Dataset | COIN, 8 skills chosen (3 target + 5 cooking, 1 held out) |
| Main model | CLIP ViT-B/16 (frozen, 86.2 M) + 2-stage MS-TCN (1.02 M trainable) + cosine heads |
| Test score (3 target skills) | **macro-F1 42.3**, F1@50 34.3, edit 45.7, ECE 3.9 % |
| Best ablation | CLIP + BiLSTM 44.3, but 3× the params and 5× the training time |
| Baseline | ResNet-50 + BiLSTM 37.9; zero-shot 16.7 |
| Training time | 1.2 min on a T4 (cached features) |
| CPU speed | 1.11 s of CPU per second of video |
| Library | **30 videos**, 4 domains, all dubbed into Hindi and Kannada |
| Cost | **₹4.07 per video**, ₹2.53 per minute of video, ₹121.98 for the library |
| Time | about **4.6 min per video** end to end on a laptop |
| Sarvam vs local TTS | 0.52 vs 3.34 s per second of audio |
| ASR agreement | Whisper vs Sarvam WER 4.5 % |
| Translation agreement | IndicTrans2 vs Sarvam chrF 75.8 (hi), 69.8 (kn) |
| Tests | 47 backend tests pass |

## 1.9 Deployment, and what to say about it

| Part | Where | Status |
|---|---|---|
| Frontend | **Vercel**: https://kaushal-dub.vercel.app | live |
| Database, auth, files | **Supabase** cloud, free tier | live, holds the 30-video library |
| Backend API + worker | **runs on our laptop** during the demo (`http://localhost:8000`) | not hosted |

**Why the backend is not hosted (for the professor):**
- The step model loads CLIP ViT-B/16 plus PyTorch, which needs about **1.5–2 GB RAM**. Free hosts (Render, Railway free tier and similar) give about 512 MB.
- Hugging Face now requires a paid PRO account for Docker Spaces. We used **only free tiers**, as the project brief requires.
- The code is ready to host: there is a Dockerfile in `deploy/hf_space/`. It is a budget decision, not a technical gap.

## 1.10 Folder map

```
kaushaldub/
  frontend/     React app (pages for trainer, learner and annotator)
  backend/      FastAPI app, worker, jobs, tests, scripts
  ml/           kd_pipeline.py (pipeline), kaushaldub_model/ (trained bundle)
  notebooks/    training (Kaggle), dub check, GPU worker
  supabase/     SQL migrations: schema, RLS, storage, full-speech
  demo/         playlist, ground truth, live demo videos, runbook, cost page
  docs/         setup, Supabase setup, hosting, paper (IEEE), team docs (this folder)
  deploy/       Hugging Face Space files (not used, needs PRO)
```

## 1.11 Limitations (be honest if asked)

- COIN labels are coarse and the test sets are small (14–23 videos per skill). BoilNoodles had only 1 test video.
- No formal listening test with learners yet, so voice quality was compared only by speed and agreement.
- The LLM can paraphrase or add small facts ("carotid"). That is why **trainer review is mandatory**.
- Only 5 skills are usable in the UI. A new skill needs labelled examples (few-shot: about 10 videos give 31 macro-F1).
- The backend is not cloud-hosted (budget).

## 1.12 Future work

- A listening test and user study with real trainees.
- Voice separation (keeping background sounds and removing only the instructor's voice) for full-speech dubbing.
- Attention-based temporal models (ASFormer).
- More skills from crowd-sourced corrections.
- More Indian languages: Sarvam and IndicTrans2 already support about 10–22.
