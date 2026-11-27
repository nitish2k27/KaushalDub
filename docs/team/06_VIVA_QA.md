# 6. Viva questions and model answers

Answers are short on purpose. Say them in your own words. ⭐ marks the **top 20** that everyone must know.

---

## A. Project and motivation

**⭐1. What does KaushalDub do?**
It turns a short English how-to video into numbered steps, editable captions, a Hindi and Kannada dubbed version, and a quiz. A trainer reviews it before learners see it.

**⭐2. Why detect steps visually instead of just translating the audio?**
- Many how-to videos have little speech or only music.
- Visual steps give a timeline that is independent of speech, keep the narration aligned with the action, and give the trainer a few sentences to review instead of a whole transcript.

**3. Who are the users?**
- Trainers create and approve content.
- Learners watch, take quizzes and report problems.
- Annotators correct step labels.

**4. Why Hindi and Kannada?**
Hindi is the most widely spoken Indian language, and Kannada is the local language in Bengaluru, where RV University is. The pipeline supports more languages; adding one means adding a language code.

**5. How is this "multimodal"?**
It combines vision (CLIP + TCN), speech (ASR and TTS) and language (LLM and translation), and the outputs of one modality feed the next.

---

## B. Dataset

**⭐6. What is COIN?**
- A CVPR 2019 dataset of 11,827 YouTube instructional videos.
- It covers 180 tasks in 12 domains and 778 step classes.
- Each video has step segments with start and end times.

**⭐7. Which classes did you choose, and why?**
- **Target skills:** ReplaceMobileScreenProtector, PerformCPR and PolishCar. They are vocational, visual and have clear steps.
- **Extra training data:** MakePizza, UseRiceCookerToCookRice, BoilNoodles and MakeCookie.
- **Held out to test few-shot learning:** CookOmelet.

**8. How many videos?**
- COIN annotates 701 videos for our 8 skills: 455 train, 81 validation (15 % of train), 165 test.
- Some YouTube videos were deleted, so we used what was downloadable.
- Testing used 89 videos: 23 screen protector, 17 CPR, 15 car, 20 pizza, 14 rice.

**9. How did you split the data?**
We used COIN's official test split. 15 % of training videos (at least 3, seed 7) became validation, used for early stopping and temperature fitting.

**10. What is "background"?**
Class 0: any frame not inside an annotated step, such as an intro, talking or showing the result.

**11. Licence issues?**
COIN annotations are CC BY-NC 4.0. We use them non-commercially. COIN distributes only YouTube IDs, not the videos.

---

## C. Computer vision model

**⭐12. Describe your model.**
- Frames at 2 fps, 224×224 → **frozen CLIP ViT-B/16** → 512-d features.
- → **2-stage MS-TCN** (6 dilated residual layers each, 128 channels).
- → **cosine heads**, one per skill, initialised from CLIP text embeddings of the step names.
- → softmax with temperature → smoothing → steps.

**⭐13. What is CLIP?**
- OpenAI's model trained contrastively on 400 M image–caption pairs.
- Its image and text encoders map into the same 512-d space, so matching images and text have high cosine similarity.
- That enables zero-shot classification.

**14. What is a Vision Transformer (ViT-B/16)?**
- The image is split into 16×16 patches (196 for 224×224), linearly embedded, with position embeddings and a CLS token.
- These go through 12 transformer layers with self-attention.
- The CLS output is projected to 512-d.

**15. Why freeze CLIP?**
- We have only hundreds of videos, and fine-tuning 86 M parameters would overfit and need a large GPU.
- Frozen features are computed once and cached, so training takes 1.2 minutes.

**⭐16. What is MS-TCN and why use it?**
- A Multi-Stage Temporal Convolutional Network (Farha & Gall, 2019).
- Dilated 1-D convolutions (dilation 1 to 32) give a receptive field of about 63 s per stage.
- The second stage refines the first.
- It is parallel (fast), has few parameters (1.02 M) and is well calibrated.

**17. What is dilated convolution?**
A convolution whose kernel taps are spaced `d` frames apart. Doubling `d` in each layer grows the receptive field exponentially without more parameters.

**18. Why multiple stages?**
Each stage refines the previous predictions, which reduces over-segmentation (label flicker).

**⭐19. What is an LSTM / BiLSTM?**
- An LSTM is an RNN with a memory cell and forget, input and output gates that control what is kept, solving vanishing gradients.
- A BiLSTM runs one LSTM forwards and one backwards in time and concatenates them, so each frame sees past and future.

**20. TCN vs LSTM: which is better?**
- In our test, CLIP + BiLSTM got 44.3 macro-F1 against 42.3 for the TCN.
- But the TCN uses 3× fewer parameters, trains 5× faster, is far better calibrated (ECE 3.9 % vs 11.7 %) and supports the cosine-head features.
- Overall the TCN gives the better trade-off.

**⭐21. What are cosine heads, and why initialise them from text?**
- Logits = scale × cosine(embedding, class vector).
- Class vectors start as CLIP text embeddings of the step names (averaged over 3 prompts).
- So the untrained model is already a zero-shot classifier.
- New skills can be added as text-plus-example prototypes, and corrections can be blended in without retraining.

**22. What is ResNet-50?**
A 50-layer CNN with skip connections, trained on ImageNet. Its 2048-d features served as our CNN-RNN baseline.

**23. What is X-CLIP?**
CLIP extended to video with cross-frame attention. We used 8-frame windows (4 s). It gave the best boundary F1 (49.0) but weak segments, because the windows blur short steps.

**⭐24. What loss function did you use?**
- Per stage: **weighted cross-entropy** (class weight ∝ 1/√count, so rare steps matter) **+ 0.15 × truncated smoothing MSE** on the change in log-probabilities between neighbouring frames, capped at 16.
- The smoothing term reduces flicker.

**25. Optimiser and hyper-parameters?**
- AdamW, learning rate 1e-3, weight decay 1e-4.
- Gradient clipping at 5.
- Up to 60 epochs with early stopping on validation macro-F1 (patience 12).
- Dropout 0.2 / 0.3. T4 GPU.

**26. What is temperature scaling? Why do you need it?**
- It divides the logits by a temperature T fitted on validation data, so the softmax confidences match real accuracy.
- We need it because a step with confidence below 0.6 is flagged for review and its keyframe goes to the LLM.

**27. What is ECE?**
- Expected calibration error.
- Predictions are binned by confidence (15 bins), and ECE is the weighted average of |accuracy − confidence|.
- Lower is better. Ours is 3.9 % raw, the best of all the models.

**28. How do you turn frame predictions into steps?**
1. Take the argmax per frame.
2. Segments under 2 s take the label of the longer neighbour.
3. Merge same-label neighbours.
4. Drop background and number the steps.
5. Confidence = mean probability.
6. Flag steps under 0.6.

**29. What happens if the model predicts only background?**
We decode again with the background class excluded, and mark all steps low-confidence so the trainer reviews them.

---

## D. Metrics and results

**⭐30. Explain macro-F1, F1@50 and edit score.**
- **Macro-F1:** frame-level F1 per class, averaged equally, so it is fair to rare steps.
- **F1@50:** a predicted segment is correct if it has the right label and IoU ≥ 50 % with a true segment.
- **Edit score:** Levenshtein similarity of the step *order*, ignoring timing.

**⭐31. What are your results?**

| Model | Macro-F1 |
|---|---|
| CLIP + MS-TCN (ours) | 42.3 (F1@50 34.3, edit 45.7, ECE 3.9 %) |
| CLIP + BiLSTM | 44.3 |
| ResNet + BiLSTM | 37.9 |
| X-CLIP | 37.4 |
| Zero-shot | 16.7 |

**32. Why not deploy the best-scoring BiLSTM?**
Its gain is only 2 points of macro-F1 with almost equal F1@50. It is 3× bigger, 5× slower to train and badly calibrated, and it cannot do prototypes or correction memory.

**33. Which skill is hardest?**
CPR (37.5). Its steps are short and look alike, for example checking breath and checking pulse. Pizza is the easiest (62.2) because its ingredients are distinct.

**34. Why is accuracy (71 %) much higher than macro-F1 (42)?**
Background frames dominate, and accuracy rewards predicting them. Macro-F1 weights every step class equally.

**35. Is 42 macro-F1 good enough?**
- For a coarse dataset with 14–23 test videos per skill, using a 1 M-parameter head, it is reasonable.
- On real videos the model found the CPR steps perfectly (edit 100, macro-F1 79.3).
- And the system makes human review mandatory, so the model only has to give a good draft.

**36. How does performance change with data?**
Macro-F1 goes 25.5 (5 videos per skill) → 29.6 (10) → 33.6 (20) → 43.9 (all). More data helps, and the correction loop collects it.

**37. What about a skill it has never seen?**
- CookOmelet with text prototypes alone gives 15.7.
- With 10 example videos and a head-only fine-tune it reaches 31.0.

---

## E. Speech, LLM, translation, dubbing

**⭐38. Walk through the pipeline for one video.**
1. ffmpeg extracts 16 kHz mono audio and 2 fps frames.
2. Sarvam ASR produces a timed transcript and detects the language.
3. CLIP + TCN finds the steps.
4. The LLM writes step text and a quiz, which are validated.
5. The trainer reviews and approves.
6. Sarvam Translate produces Hindi and Kannada.
7. Bulbul TTS voices each step.
8. Clips are placed on their steps (speed-up of at most 1.3×), mixed over the original at 15 %, VTT captions are written, and ffmpeg muxes everything into the mp4.

**39. How are audio and video separated?**
- ffmpeg `-vn -ac 1 -ar 16000` gives the audio WAV.
- `fps=2, scale/crop 224` gives raw RGB frames.
- At the end, ffmpeg copies the original video stream unchanged and mixes the new audio in.

**40. Which ASR do you use, and why not Whisper?**
- Sarvam by default. It handles Indian languages and English, auto-detects the language, and costs ₹0.49 per minute.
- Whisper-small also works (WER 4.5 % against Sarvam), but it needs a 47 s model load and added a spurious "Music" tag.
- IndicConformer is free but handles Indian languages only.

**⭐41. How do you stop the LLM from hallucinating?**
- The prompt gives only the transcript inside each step and the step label, with a word budget.
- It explicitly forbids adding facts.
- The output is validated (same step count and order), retried once, and replaced with a template if it still fails.
- The trainer review is mandatory.
- On the CPR video, 76.5 % of the content words were directly supported, and the "extra" words were mostly paraphrases.

**42. Which LLM?**
- Gemini Flash (the newest is auto-selected), then a second Gemini model, then Groq GPT-OSS-120B, then a template.
- In the 30-video batch Gemini was often overloaded: Groq wrote 29 of the videos and the template was never needed.

**43. How do you keep the narration in sync?**
- A word budget of about 2 words per second.
- Each clip starts at its step.
- A clip that is too long is sped up (up to 1.3×, pitch kept by ffmpeg atempo).
- Overflow pushes the next clip later, so the order is never broken.
- In the CPR test only one clip needed a speed-up (1.036×).

**44. Sarvam vs AI4Bharat open models?**

| Stage | Sarvam | AI4Bharat / open |
|---|---|---|
| Translation | fast; chrF agreement with IndicTrans2 is 75.8 hi / 69.8 kn | IndicTrans2, free |
| TTS | Bulbul: 0.52 s per second of audio | Indic Parler: 3.34 s per second on a T4 |
| Cost | ₹4 per video, good for interactive use | ₹0, good for bulk jobs on a free GPU |

**45. What is "full-speech mode"?**
Instead of short per-step narration, every transcript sentence is translated and voiced at its own time, with the original audio at 5 %. It suits talk-heavy tutorials.

**46. What does a dub cost?**
₹4.07 on average per video (₹2.53 per minute of source video) for Hindi + Kannada. The whole 30-video library cost ₹121.98, at about 4.6 minutes per video.

---

## F. System, security and engineering

**⭐47. Explain the architecture.**
- The React frontend is on Vercel.
- Supabase provides Google auth, Postgres with RLS and storage.
- The FastAPI backend verifies the JWT and enqueues jobs on Redis (RQ).
- A worker runs the pipeline and writes results back.
- The frontend polls job progress.

**48. Why a job queue?**
Processing takes minutes. The API returns immediately with a job id, the worker does the heavy work, and the UI polls `/jobs/{id}`.

**49. How is security handled?**
- Google OAuth.
- JWT verified on every API call.
- Row Level Security so users only see their own or published rows.
- Private buckets with expiring signed URLs.
- User API keys encrypted with Fernet (AES-128 + HMAC), never returned in full and never logged.
- Secrets live only in `.env`.

**50. What is Row Level Security?**
Postgres policies that filter rows per user, for example `owner = auth.uid()` or `published = true`. Even a leaked anon key cannot read other people's data.

**51. What happens when API credits run out?**
- HTTP 402 means out of credits: no retry, fall back to the next provider.
- HTTP 429 means rate limited: retry with back-off.
- If no provider is left, the job pauses as `needs_credits` with a clear message.
- A monthly budget cap also stops platform-key jobs.

**52. How do the plans work?**
- **Free:** the first 5 videos on platform keys, enforced on the server.
- **BYOK:** the user's own encrypted keys.
- **Local:** AI4Bharat models on a GPU worker.
- **Pro:** "coming soon".

**⭐53. Why isn't the backend hosted?**
- The model needs about 1.5–2 GB RAM (PyTorch + CLIP), while free hosts give about 512 MB.
- Hugging Face Docker Spaces now need PRO.
- We kept to free tiers, as the brief requires.
- The frontend is live on Vercel and the database on Supabase. The backend runs on our laptop, and a Dockerfile is ready.

**54. How did you test it?**
- 47 automated backend tests (pytest), including end to end with mocked providers, plans, tickets, annotations, auth and the queue.
- A batch of 30 real videos.
- Ground-truth scoring of the step model.

---

## G. Human-in-the-loop and learning

**⭐55. How do annotator corrections improve the model?**
- Approved corrected segments store their embeddings in the correction memory.
- The next prediction for that skill blends them into the class vectors: `α = max(0.5, 5/(5+n))`.
- That is an immediate improvement without retraining.
- At 20 pending corrections a retrain job runs, and the new model is activated only if its test macro-F1 is not worse.

**56. Is this reinforcement learning?**
No. It is **active learning with a human oracle**: humans provide verified labels, with no reward signal or policy.

**57. Why does the trainer have to approve annotator changes?**
For quality control. A wrong correction would poison the memory, so each change is approved individually.

**58. What do learner reports do?**
- They capture the timestamp, step, language and category.
- The trainer edits that step's text in that language and re-voices only that step (a revoice job), then replies.
- The learner sees the status.

---

## H. Critical and tricky questions

**59. What are the limitations?**
- Small test sets and coarse COIN labels.
- No listening test.
- The LLM can paraphrase or add facts.
- Only 5 usable skills.
- The backend is not cloud-hosted.

**60. What would you do with more time or money?**
- A user study and listening test.
- Voice separation for full-speech mode.
- ASFormer or transformer temporal models.
- More skills and languages.
- GPU hosting.

**61. What if the trainer selects the wrong skill?**
The model uses that skill's step vocabulary, so the steps will be wrong and low-confidence. The trainer sees this in review. Automatic skill classification is future work.

**62. Could this be misused for unsafe instructions?**
- Review is mandatory.
- Learners can report "Unsafe instruction".
- The prompt forbids added facts.

**63. Why only 2 fps?**
Steps last several seconds. 2 fps localises them to about 0.5 s and keeps CPU inference at about 1.1× real time.

**64. Why not fine-tune a video LLM (like Gemini on the video)?**
- Cost, privacy and control.
- Our step model is small, local, measurable, calibrated and improvable with corrections.
- The LLM only writes text from the detected steps.

**65. What was the hardest part?**
- Making the stages robust (fallbacks for 402/429/503, LLM validation and repair).
- Getting the narration timing right.
- Handling videos with no speech or no detected steps.

**66. What did each team member do?**
Prepare your own honest answer before the viva.
