# Live demo videos

Fresh COIN **test** videos: not in the library and never seen by the step model in training. Chosen out of six
candidates by scoring the trained model against COIN's ground-truth steps (`demo/live_candidates/check.log`).

| File | Skill | Length | Model score (macro-F1) | What the model finds |
|---|---|---|---|---|
| `1_pizza_deep_dish.mp4` | Make pizza (Cooking) | 1:53 | **68.8** | knead the dough → unroll the dough → add seasoning, in the right order |
| `2_screen_protector_sparin.mp4` | Replace a screen protector (Phone repair) | 1:34 | **54.1** | wipe the screen → line up the protector → paste it on |
| `3_car_polishing_uae.mp4` | Polish a car (Car care) | 1:00 | 49.9 | clean the scratch, apply paste, polish with polisher (several short low-confidence steps) |
| `backup_cpr_st_john.mp4` | Perform CPR (First aid) | 1:15 | 36.6 | chest compressions found at the right times; one false step at the start |

The model's test-set average is 42.3, so 1 and 2 are better than typical and 3 is about typical.

## Running it in front of the professor

Processing on the laptop takes about 4–5 minutes per video (step detection on CPU about 1–2 min, Sarvam and the LLM
about 1–2 min, dubbing about 1 min). Plan it like this:

1. **Start the upload first**: Trainer → My videos → choose `1_pizza_deep_dish.mp4`, title "Deep dish pizza", skill
   **Make pizza**, spoken language **Detect automatically**, Hindi + Kannada → Process. The stage list shows each step.
2. **While it runs**, show the library (about 30 videos already dubbed), a learner watching in Kannada, the quiz, a
   learner report and the trainer fixing it, the annotator screen, and the cost page.
3. **When it reaches Review**, show the detected steps with confidence pills and the low-confidence warning, edit one
   narration, then **Approve and create dub**. About 1 minute later, play it in Hindi and Kannada and publish.
4. If there's time, do `2_screen_protector_sparin.mp4` the same way. Keep `3_…` and the backup for questions.

Each live video costs about ₹4–8 of Sarvam credit. Check the day before that the Supabase project is active (free
projects pause after a week without use) and that the Sarvam balance is above ₹30.
