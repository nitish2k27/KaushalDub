# KaushalDub team handbook (demo + viva prep)

Read these in order. Each one is self-contained.

| # | Doc | What's inside | Who must read |
|---|---|---|---|
| 1 | [01_PROJECT_OVERVIEW.md](01_PROJECT_OVERVIEW.md) | problem, idea, roles, features, key numbers, deployment, limitations | **everyone** |
| 2 | [02_DATASET.md](02_DATASET.md) | what COIN is, the 8 skills we chose and why, video counts, splits, preprocessing | everyone; CV owner in depth |
| 3 | [03_CV_MODEL.md](03_CV_MODEL.md) | CLIP, ViT, MS-TCN, BiLSTM, cosine heads, loss, training, the 5 models compared, all results | CV owner in depth; everyone the summary |
| 4 | [04_SYSTEM_FLOW.md](04_SYSTEM_FLOW.md) | one video traced through every stage: ffmpeg split, ASR, step model, LLM, review, translate, TTS, placement, mux | everyone |
| 5 | [05_DEMO_PREP.md](05_DEMO_PREP.md) | who does what, the day-before checklist, start commands, minute-by-minute script, what to do if something breaks | **everyone** |
| 6 | [06_VIVA_QA.md](06_VIVA_QA.md) | 66 likely viva questions with short answers (⭐ = top 20) | **everyone** |

**Fastest prep (1 hour):**
1. Doc 1.
2. The ⭐ questions in doc 6.
3. Doc 5 §5.4 (the demo script).

**Live app:** https://kaushal-dub.vercel.app (frontend). The backend runs on the laptop during the demo.
**Paper:** `docs/paper/kaushaldub_ieee.tex` (all the numbers here match it and `docs/paper/metrics.json`).
