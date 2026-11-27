# 5. Demo preparation guide for the team

## 5.1 Who does what (suggested split; agree on it as a team)

| Person | Owns in the demo | Must master |
|---|---|---|
| **A: Intro + Trainer flow** | problem, idea, live upload → review → approve → dub → publish | docs 1 and 4 |
| **B: Computer vision** | step model, dataset, architecture comparison, results | docs 2 and 3 |
| **C: Speech + LLM + system** | ASR, LLM grounding, translation, TTS, placement, cost, Sarvam vs local | doc 4, §1.8 in doc 1 |
| **D: Learner + Annotator + loops** | library, Kannada watch, quiz, report → fix, annotator correction → approval → correction memory, plans and keys | docs 1 (§1.7) and 4 (§4.13) |

**Everyone** should be able to answer the top 20 viva questions in [06_VIVA_QA.md](06_VIVA_QA.md).

---

## 5.2 The day before (checklist)

- [ ] **Supabase project is active.** Free projects pause after about a week of no use. Open the dashboard and click "Restore" if it is paused.
- [ ] **Sarvam balance is above ₹30** (dashboard.sarvam.ai). One live video costs about ₹4–8.
- [ ] The Gemini and Groq keys in `.env` still work. Groq is the backup if Gemini is overloaded.
- [ ] Laptop charged; close Chrome tabs. The model needs about 2 GB RAM.
- [ ] Do a **full dry run** with `demo/live/2_screen_protector_sparin.mp4`, then delete that test video.
- [ ] Have `demo/live/` open in File Explorer.
- [ ] (Optional, for using the Vercel URL) in Supabase Redirect URLs, Google OAuth origins and `CORS_ORIGINS`, add `https://kaushal-dub.vercel.app`. Otherwise use `http://localhost:5173`.
- [ ] Have the paper PDF and `demo/cost_page.html` ready in tabs.

## 5.3 Starting the app on demo day (about 2 minutes)

Run these from the `kaushaldub` folder, in **two terminals**.

Terminal 1, the backend (API + worker):

```bash
backend\.venv\Scripts\python backend\scripts\dev.py
```

Wait until it prints `Uvicorn running on ...:8000`.

Terminal 2, the frontend:

```bash
cd frontend
npm run dev
```

Then open **http://localhost:5173**, or https://kaushal-dub.vercel.app if step 5.2's optional config is done. Sign in with Google and pick the **Trainer** role.

Quick health check: http://localhost:8000/docs should show the API page.

---

## 5.4 Demo script (about 12–15 minutes)

| Time | Who | What to do / say |
|---|---|---|
| 0:00 | A | **Problem** (30 s): "Skill videos are in English; trainees learn better in Hindi and Kannada. Translating audio fails when there is little speech." **Idea:** "We detect steps visually, then narrate each step." |
| 1:00 | A | **Start the live upload first**, because it takes about 4–5 min. Use Trainer → My videos → `1_pizza_deep_dish.mp4`, title "Deep dish pizza", skill **Make pizza**, spoken language **Detect automatically**, Hindi + Kannada, Step narration → **Process**. Show the stage list starting. |
| 2:00 | B | **While it runs:** explain the step model with a slide or doc 3's diagram: CLIP → MS-TCN → cosine heads. Show the results table: "42.3 macro-F1; we compared 5 architectures." |
| 4:00 | D | Switch to **Learner** → Library (30 videos, 4 domains) → open a CPR video → switch to **Kannada** → click a step in the list → take the **quiz**. |
| 5:30 | D | **Report a problem** at a timestamp (category Wrong translation) → switch to **Trainer → Learner reports** → open it → the player jumps → edit the text → **Re-make voice** → reply and resolve. |
| 7:00 | D | **Annotator** → queue → open a clip → move a boundary or change a label → submit → **Trainer → Annotation requests** → compare the two timelines → approve → show the **Model learning** card (correction memory count). |
| 8:30 | A | Back to the pizza job, which should now be at **Review**. Show the step ticks, confidence pills and the **low-confidence warning**. Edit one narration. **Approve and create dub.** |
| 9:00 | C | While it dubs: explain ASR → LLM grounding (word budget, no added facts) → translation → TTS → placement (speed-up of at most 1.3×) → mux with the original audio at 15 %. Show the **cost page** (₹4 per video). |
| 10:00 | A | **Result:** play in **Hindi**, then **Kannada**; show the captions → **Publish**. |
| 11:00 | C | **API keys & plan** tab: free trial counter, BYOK with encrypted keys, local models, Pro "coming soon". Mention the 402/429 handling. |
| 12:00 | All | Limitations + future work, then questions. |

### If something goes wrong

| Problem | What to do |
|---|---|
| Live job is slow (Gemini overloaded) | Carry on with the other parts; the job falls back to Groq automatically. Show the stage log. |
| Job shows `needs_credits` | "This is our out-of-credit handling working." Show an already-dubbed library video instead. |
| No internet | Show the library videos already made. Explain with the docs and the paper. |
| Model finds odd steps | "That's why review is mandatory." Edit them live. That is a feature of the design. |
| Login fails on Vercel | Use `http://localhost:5173`. Its redirect is already configured. |
| Backend crashes | Restart Terminal 1. Jobs are stored in the database. |

Backup video: `demo/live/backup_cpr_st_john.mp4` (75 s, faster to process).

---

## 5.5 Things to show if asked

| Asked about | Show |
|---|---|
| Training | `notebooks/kaushaldub_train.ipynb` |
| Model files | `ml/kaushaldub_model/config.json` (vocabulary, temperatures), `model.pt` (4 MB) |
| Database + security | Supabase dashboard → Table editor, and `supabase/migrations/*_rls.sql` |
| Tests | `backend\.venv\Scripts\python -m pytest backend/tests -q` (47 pass) |
| API | http://localhost:8000/docs |
| Paper | `docs/paper/kaushaldub_ieee.tex` (Overleaf PDF) |
| Costs | `demo/cost_page.html`, `demo/batch_results_sarvam.csv` |

## 5.6 One-minute elevator pitch (everyone memorise)

> "KaushalDub turns English how-to videos for vocational skills, such as CPR, phone repair, car care and cooking, into Hindi and Kannada versions. Instead of translating the audio word for word, we first find the steps visually. Frozen CLIP features go through a temporal convolutional network that we trained on the COIN dataset, which reaches 42 macro-F1 and is the best-calibrated of the five architectures we compared. An LLM writes a short, grounded instruction for each step. A trainer reviews it. Sarvam then translates and voices it, and we place each clip on its step and mix it into the video with captions and a quiz. Learners can report problems, and annotator corrections improve the model through a correction memory. A dub costs about four rupees and five minutes per video."
