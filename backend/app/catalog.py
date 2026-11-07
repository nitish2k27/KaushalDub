"""Skills the step model was trained on (BoilNoodles and MakeCookie are excluded: too few videos)."""
TASKS = {
    "PerformCPR": {"title": "Perform CPR", "domain": "First aid"},
    "ReplaceMobileScreenProtector": {"title": "Replace a phone screen protector", "domain": "Phone repair"},
    "PolishCar": {"title": "Polish a car", "domain": "Car care"},
    "MakePizza": {"title": "Make pizza", "domain": "Cooking"},
    "UseRiceCookerToCookRice": {"title": "Cook rice in a rice cooker", "domain": "Cooking"},
    "CookOmelet": {"title": "Cook an omelette", "domain": "Cooking", "fewshot": True},
}
DOMAINS = sorted({t["domain"] for t in TASKS.values()})
LANGS = {"en": "English", "hi": "Hindi", "kn": "Kannada"}
TARGET_LANGS = ["hi", "kn"]
CATEGORIES = ["Wrong step", "Wrong translation", "Narration out of sync", "Unclear instruction",
              "Unsafe instruction", "Other"]
ASR = ["whisper", "indicconformer", "sarvam"]
MT = ["indictrans2", "sarvam"]
TTS = ["indicparler", "sarvam"]
LOCAL = {"whisper", "indicconformer", "indictrans2", "indicparler"}
GPU_ONLY = {"indicconformer", "indicparler"}     # too slow for the CPU Space
NEEDS_SARVAM = {"sarvam"}
