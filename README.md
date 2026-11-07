# KaushalDub

Skill videos in the language people work in.

## The problem

Short how-to videos are a common way to teach vocational skills such as CPR, phone repair, car care or cooking.
Most of them are narrated in English, so many learners who work in Hindi or Kannada cannot follow them, and
re-recording every video in every language is slow and expensive.

## Our solution

KaushalDub takes a how-to video and automatically:

1. **finds the steps** with a trained vision model (CLIP + temporal convolutional network),
2. **writes a short instruction** for each step from what the instructor says (LLM),
3. **dubs it into Hindi and Kannada** with captions, timed to each step,
4. **makes a quiz** for learners.

A trainer reviews and publishes the result, learners watch it in their language and can report mistakes, and
annotators correct the model, which learns from every approved correction.

## Tech stack

| Part | Tools |
|---|---|
| Frontend | React, Vite, TypeScript, Tailwind CSS, shadcn/ui |
| Backend | FastAPI (Python), Redis + RQ job queue |
| Database, login, files | Supabase (Postgres, Google sign-in, Storage) |
| Step model | CLIP ViT-B/16 + MS-TCN (PyTorch), trained on COIN |
| Speech, translation, voice | Sarvam AI, or open AI4Bharat models (IndicTrans2, Indic Parler-TTS), Whisper |
| Step text and quiz | Gemini, Groq (fallback) |
| Hosting | Vercel (frontend), Hugging Face Spaces (backend), Kaggle GPU (optional worker) |

## Get the code

```bash
git clone https://github.com/<your-username>/kaushaldub.git
cd kaushaldub
```

```bash
cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
```

```bash
cd frontend && npm install
```

Copy `.env.example` to `.env`, add your keys, then run `backend/scripts/dev.py` and `npm run dev` in `frontend/`.
Full setup, Supabase and deployment steps: [docs/SETUP.md](docs/SETUP.md).

## Folder structure

```
kaushaldub/
├── frontend/          React app (trainer, learner and annotator screens)
├── backend/
│   ├── app/           FastAPI routes, job worker, plans, providers
│   ├── scripts/       dev server, batch processing, setup check, migration
│   └── tests/         automated tests (pytest)
├── ml/                dubbing pipeline (kd_pipeline.py) and step model (kd_model.py)
├── supabase/          SQL migrations: tables, security rules, storage
├── notebooks/         training, pipeline check, GPU worker
├── demo/              playlist of test videos and live-demo script
├── docs/              setup guide, paper, images
└── design/            original UI mockup
```

## System design

```mermaid
flowchart LR
    U[Web app<br/>React on Vercel] -->|REST + JWT| A[FastAPI<br/>Hugging Face Space]
    U -->|Google sign-in| S[(Supabase<br/>Postgres + Storage)]
    A --> S
    A -->|jobs| Q[Redis queue]
    Q --> W1[CPU worker]
    Q --> W2[GPU worker<br/>Kaggle, optional]
    W1 --> P[Sarvam / Gemini / Groq APIs]
    W2 --> L[AI4Bharat open models]
    W1 --> S
    W2 --> S
```

## How a video is processed

```mermaid
flowchart LR
    V[Video] --> A[Audio + speech to text]
    A --> B[Step detection<br/>CLIP + MS-TCN]
    B --> C[Step text + quiz<br/>LLM]
    C --> R{Trainer review}
    R -->|approve| D[Translate<br/>Hindi, Kannada]
    D --> E[Text to speech]
    E --> F[Place clips on steps,<br/>mix audio, captions]
    F --> G[Dubbed video<br/>in the library]
    B -. corrections .-> H[Annotator] -. approved .-> M[Correction memory<br/>+ retraining]
    M -.-> B
```

Each stage has a fallback (for example Sarvam → open model, Gemini → Groq → template). If every provider runs out
of credits, the job pauses and the trainer can resume it later.

## Step model

```mermaid
flowchart LR
    F[Video frames<br/>2 per second] --> E[CLIP ViT-B/16<br/>frozen]
    E --> T[2-stage temporal<br/>conv network]
    T --> H[Cosine heads,<br/>one per skill]
    H --> S[Steps with<br/>start, end, confidence]
```

Compared with ResNet-50 + BiLSTM, X-CLIP and CLIP zero-shot on COIN, it gives 42.3 macro-F1 with only 1 M
trainable parameters and the best calibration. Details are in the [paper](docs/paper/kaushaldub_ieee.tex).

## Database design

<!-- Supabase screenshot: save it as docs/images/database.png and remove these comment marks
![Database schema from Supabase](docs/images/database.png)
-->

```mermaid
erDiagram
    users ||--o{ videos : uploads
    users ||--|| user_plans : has
    users ||--o{ user_api_keys : stores
    videos ||--o{ steps : has
    steps ||--o{ translations : "translated into"
    videos ||--o{ outputs : "dubbed as"
    videos ||--o| quizzes : has
    quizzes ||--o{ quiz_attempts : "answered in"
    videos ||--o{ watch_history : "watched in"
    videos ||--o{ tickets : "reported in"
    videos ||--o{ annotations : "labelled in"
    videos ||--o{ annotation_requests : "corrected in"
    annotation_requests ||--o{ correction_memory : feeds
    videos ||--o{ jobs : "processed by"

    users {
        uuid id PK
        text email
        text name
        text role
    }
    videos {
        uuid id PK
        uuid owner FK
        text title
        text task
        text status
        text dub_mode
        bool published
    }
    steps {
        uuid id PK
        uuid video_id FK
        int idx
        float start_s
        float end_s
        text label
        float confidence
        text narration_en
    }
    translations {
        uuid step_id FK
        text lang
        text text
    }
    outputs {
        uuid video_id FK
        text lang
        text mp4_path
        text vtt_path
    }
    tickets {
        uuid id PK
        uuid video_id FK
        uuid reporter_id FK
        float timestamp_s
        text category
        text status
        text reply
    }
    annotation_requests {
        uuid id PK
        uuid video_id FK
        jsonb changes
        text status
    }
    jobs {
        uuid id PK
        uuid video_id FK
        text kind
        text stage
        int progress
        jsonb cost
    }
```

Also: `user_plans` (free trial counter, model choice), `user_api_keys` (encrypted keys), `quizzes`,
`quiz_attempts`, `watch_history`, `annotations`, `correction_memory`, `model_versions`. Every table has row-level
security.

## API design

All routes need a Supabase login token (`Authorization: Bearer <token>`).

| Method | Route | What it does |
|---|---|---|
| POST | `/videos` | Upload a video (file or YouTube link) and start processing |
| GET | `/videos` | My uploaded videos |
| GET | `/videos/{id}` | Video with steps, quiz and dubbed files |
| PATCH | `/videos/{id}/steps` | Edit step text |
| POST | `/videos/{id}/approve` | Create the dub (step narration or full speech) |
| POST | `/videos/{id}/publish` | Add to the learner library |
| GET | `/jobs/{id}` | Progress of a job, stage by stage |
| GET | `/library` | Search published videos |
| POST | `/quiz/{video_id}/attempts` | Submit quiz answers |
| POST | `/videos/{id}/tickets` | Learner reports a problem at a timestamp |
| GET / PATCH | `/tickets/{id}` | Trainer fixes, replies and closes a report |
| GET / PUT | `/annotations/{clip_id}` | Annotator loads and saves step labels |
| POST | `/annotation-requests/{id}/approve` | Trainer approves selected corrections |
| GET / POST | `/model/status`, `/model/retrain` | Model learning status and retraining |
| GET / PUT | `/me/plan`, `/me/keys/{provider}` | Plan, model choice and own API keys |

The full, interactive list is at `/docs` on the running backend.

## Results so far

- 30 COIN test videos dubbed into Hindi and Kannada across four domains
- About **Rs. 4 and 4–5 minutes per video** with Sarvam, or free with open models on a GPU
- 47 automated tests pass

## What could be improved

- A listening test with real learners to rate voice quality
- More skills, by collecting corrections from annotators
- Removing the original voice cleanly in full-speech mode (voice separation)
- Running the step model on a GPU in production to cut processing time

---

RV University, CS3235 (Module 3: Multimodal AI) coursework. COIN annotations are CC BY-NC 4.0.
