# 2. Dataset: COIN and what we used

## 2.1 What is COIN?

**COIN** stands for **CO**mprehensive **IN**structional video analysis. It is a public research dataset published at CVPR 2019 by Tang et al. (Tsinghua University and Meitu).

| Fact | Value |
|---|---|
| Total videos | **11,827** YouTube how-to videos |
| Tasks (we call them "skills") | **180**, for example PerformCPR, MakePizza or PolishCar |
| Domains | 12, for example vehicles, gadgets, dish, health or house |
| Step classes | 778 named steps across all tasks |
| Total length | about 476 hours |
| Annotation | each video has **step segments**: `[start_s, end_s, step label]` |
| Splits | the authors provide an official `training` / `testing` split |
| Licence | annotations are CC BY-NC 4.0 (non-commercial). The videos stay on YouTube, and COIN gives only IDs and labels. |

**What one COIN annotation looks like** (simplified):

```json
"bEBEOuaQcag": {
  "class": "PerformCPR",
  "subset": "testing",
  "duration": 95.3,
  "annotation": [
    {"segment": [31, 34], "label": "check the foreign matter in the mouse"},
    {"segment": [35, 44], "label": "check the breath of the patient"},
    {"segment": [48, 72], "label": "press the chest of the patient"},
    {"segment": [80, 85], "label": "do artificial breathing to the patient"}
  ]
}
```

Any time that is not inside a segment counts as **background**: talking to the camera, intro, outro, showing the result.

**Why COIN and not another dataset?**
- It has **step-level time stamps**, which is exactly what we need. Kinetics, for example, gives only one label per clip.
- It covers **vocational and practical** skills such as first aid, phone repair, car care and cooking, which fits the project brief ("Kaushal" = skill).
- Its step names are in plain English ("press the chest of the patient"). That lets us initialise the classifier from CLIP **text** embeddings (see doc 3).
- Alternatives we considered: CrossTask (18 tasks only, mostly cooking), Breakfast (cooking only, recorded in a lab), YouCook2 (cooking only).

## 2.2 Which classes (skills) we chose, and why

We picked **8 COIN tasks** in three roles:

| Role | Skill (COIN task) | Domain in our app | Why |
|---|---|---|---|
| **Target** (main skills) | ReplaceMobileScreenProtector | Phone repair | vocational, visual, clear steps |
| **Target** | PerformCPR | First aid | a life-saving skill, high social value |
| **Target** | PolishCar | Car care | a common job-oriented skill |
| Extra training data | MakePizza | Cooking | adds more labelled video, so the model generalises |
| Extra training data | UseRiceCookerToCookRice | Cooking | same |
| Extra training data | BoilNoodles | Cooking | trained, but most of its YouTube videos were unavailable |
| Extra training data | MakeCookie | Cooking | trained, but very few videos downloaded; hidden in the UI |
| **Held out** (few-shot test) | CookOmelet | Cooking | **never trained on**. Used to test whether a new skill can be added from a few examples. |

Selection logic, in one line: we chose three vocational target skills, plus cooking tasks that add data and include one unseen skill for the few-shot experiment.

### Step classes per skill (the "vocabulary")

Class 0 is always `background`. The list below comes straight from `ml/kaushaldub_model/config.json`:

| Skill | Step classes (excluding background) |
|---|---|
| ReplaceMobileScreenProtector (4) | wipe the screen · remove the original protector · paste protector on the screen · line up the protector and the cellphone |
| PerformCPR (6) | press the chest of the patient · do artificial breathing · check the breath · check the pulse · check the foreign matter in the mouth* · call emergency number |
| PolishCar (4) | clean the scratch · polish with polisher · apply polishing paste on the surface · clean the surface |
| MakePizza (4) | add seasoning · unroll the dough · bake pizza · knead the dough |
| UseRiceCookerToCookRice (4) | cook the rice by rice cooker · put the washed rice into the cooker · take out some rice · soak and wash the rice |
| BoilNoodles (4) | pour noodles into water and stir · pour the cooked noodles · add seasoning to boiling water · taste the noodles |
| MakeCookie (4) | pour raw materials · mix raw materials · shape cookie · bake cookies |
| CookOmelet (6) | fry eggs · pour egg into the pot · stir the egg · pour egg onto the plate · pour egg into the bowl · put seasoning in the egg |

\* COIN's label actually says "mouse", a typo for "mouth". The code fixes it before making the text embeddings.

That gives 36 step classes plus a background class for each skill, 44 classes in total across the 8 heads.

## 2.3 How many videos

### Annotated in COIN, for our 8 skills

We kept COIN's official test split. **15% of the training videos** (at least 3, random seed 7) became the **validation** split. The validation split is used for early stopping and for fitting the temperature.

| Skill | All in COIN | Train | Val | Test | Avg length | Avg steps / video |
|---|---|---|---|---|---|---|
| ReplaceMobileScreenProtector | 113 | 73 | 13 | 27 | 151 s | 5.9 |
| PerformCPR | 87 | 58 | 10 | 19 | 132 s | 5.1 |
| PolishCar | 76 | 50 | 9 | 17 | 145 s | 4.8 |
| MakePizza | 88 | 56 | 10 | 22 | 146 s | 4.2 |
| UseRiceCookerToCookRice | 101 | 65 | 12 | 24 | 139 s | 3.6 |
| BoilNoodles | 97 | 62 | 11 | 24 | 150 s | 2.8 |
| MakeCookie | 46 | 31 | 5 | 10 | 153 s | 5.6 |
| CookOmelet (held out) | 93 | 60 | 11 | 22 | 151 s | 4.1 |
| **Total** | **701** | **455** | **81** | **165** | | |

### Actually usable

COIN gives YouTube IDs only, and many videos have since been deleted or made private, so we could not download all of them. The **test videos we actually evaluated on** are:

| Skill | Test videos used |
|---|---|
| ReplaceMobileScreenProtector | 23 |
| PerformCPR | 17 |
| PolishCar | 15 |
| MakePizza | 20 |
| UseRiceCookerToCookRice | 14 |
| BoilNoodles | 1 (so its score is not reliable) |
| MakeCookie | 0 |

Training used the same cached features for whatever train and validation videos were downloadable. Videos were downloaded with `yt-dlp` at **360p or lower, video stream only**: training needs no audio, and the smaller files are faster to process.

**If asked "how many videos did you train on?"**, say: about 450 annotated training videos across 7 skills in COIN; we trained on the ones still available on YouTube; testing used 89 videos across the three target skills and the two main cooking skills.

## 2.4 Preprocessing

1. **Manifest** (`ml/prepare_coin.py`, also the first cell of `notebooks/kaushaldub_train.ipynb`). This step reads `COIN.json`, keeps our 8 tasks, builds each task's vocabulary (background first, then steps ordered by frequency) and assigns train, val or test to each video.
2. **Frames.** ffmpeg decodes each video at **2 frames per second**, scales and centre-crops it to **224×224**, and stops at **900 frames** (7.5 minutes).
3. **Frame labels.** Each sampled frame gets the class of the COIN segment it falls in, or 0 for background. A 120 s video therefore becomes 240 frames and 240 labels.
4. **Features (cached once).** Each frame goes through the frozen encoder (CLIP, ResNet-50 or X-CLIP) and is saved as a `.npy` file. Training then works on these small feature files, which is why a training run takes only minutes.

## 2.5 Our own demo and library sets (not for training)

| Set | Where | What |
|---|---|---|
| Library playlist | `demo/playlist.csv`, `demo/PLAYLIST.md` | **30 COIN test videos** (5 CPR, 5 screen protector, 5 car polishing, 15 cooking: 5 pizza, 5 rice, 5 omelette), all dubbed into Hindi and Kannada with Sarvam and stored in Supabase |
| Ground truth | `demo/ground_truth.json` | COIN step times for those videos, used for scoring |
| Live demo videos | `demo/live/` | 3 fresh test videos plus 1 backup, never seen in training (pizza 68.8, screen protector 54.1, car 49.9, CPR 36.6 macro-F1) |
| Unseen CPU check | in `docs/paper/metrics.json` | 10 further videos run on a laptop CPU: mean macro-F1 41.0 (range 25.0–68.8), 1.11 s of CPU per second of video |

All of these are **test-split** videos, so the model never saw them during training. That keeps the demo honest.
