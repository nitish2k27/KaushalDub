"""KaushalDub step recogniser: models, frame reading, feature encoders and inference.

Main model: frozen CLIP ViT-B/16 frame features -> multi-stage temporal conv net (MS-TCN
style) -> cosine heads, one per task, initialised from CLIP text embeddings of the step
names. Baselines: ResNet-50 features + BiLSTM, X-CLIP features + linear head."""
import json, math, os, subprocess
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from kd_metrics import softmax, decode

CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
CLIP_STD = (0.26862954, 0.26130258, 0.27577711)
IMNET_MEAN = (0.485, 0.456, 0.406)
IMNET_STD = (0.229, 0.224, 0.225)
PROMPTS = ["{}", "a video of a person who is about to {}", "how to {}: a step in a tutorial video"]
BG_PROMPTS = ["a person talking to the camera", "the title screen or introduction of a tutorial video",
              "a finished result being shown at the end of a video"]


# ---------------------------------------------------------------- frames
def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def read_frames(path, fps=2, size=224, max_frames=900):
    """Decode a video at `fps` frames per second, resized and centre-cropped to size x size.
    Returns uint8 array [T, size, size, 3]."""
    vf = f"fps={fps},scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size}"
    cmd = [ffmpeg_exe(), "-loglevel", "error", "-i", path, "-vf", vf, "-frames:v", str(max_frames),
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    out = subprocess.run(cmd, capture_output=True, check=False).stdout
    return np.frombuffer(out, np.uint8).reshape(-1, size, size, 3)


def _to_tensor(frames, mean, std, device):
    x = torch.from_numpy(np.array(frames, copy=True)).to(device).permute(0, 3, 1, 2).float() / 255
    m = torch.tensor(mean, device=device).view(1, 3, 1, 1)
    s = torch.tensor(std, device=device).view(1, 3, 1, 1)
    return (x - m) / s


# ---------------------------------------------------------------- encoders
class ClipEncoder:
    name, dim = "clip", 512

    def __init__(self, device):
        import open_clip
        self.model, _, _ = open_clip.create_model_and_transforms("ViT-B-16-quickgelu", pretrained="openai")
        self.model = self.model.to(device).eval().half() if device != "cpu" else self.model.eval()
        self.tok = open_clip.get_tokenizer("ViT-B-16-quickgelu")
        self.device = device

    @torch.no_grad()
    def frames(self, frames, bs=128):
        out = []
        for i in range(0, len(frames), bs):
            x = _to_tensor(frames[i:i + bs], CLIP_MEAN, CLIP_STD, self.device)
            if self.device != "cpu":
                x = x.half()
            out.append(F.normalize(self.model.encode_image(x).float(), dim=-1).cpu())
        return torch.cat(out).numpy() if out else np.zeros((0, self.dim), np.float32)

    @torch.no_grad()
    def text(self, sentences):
        t = self.tok(sentences).to(self.device)
        return F.normalize(self.model.encode_text(t).float(), dim=-1).cpu().numpy()

    def step_embeddings(self, steps):
        """steps: ['background', 'wipe the screen', ...] -> [C, 512] averaged over prompts."""
        rows = []
        for s in steps:
            s = s.replace("in the mouse", "in the mouth")      # typo in the COIN label
            sents = BG_PROMPTS if s == "background" else [p.format(s) for p in PROMPTS]
            e = self.text(sents).mean(0)
            rows.append(e / np.linalg.norm(e))
        return np.stack(rows).astype(np.float32)


class ResNetEncoder:
    name, dim = "resnet", 2048

    def __init__(self, device):
        import torchvision
        m = torchvision.models.resnet50(weights=torchvision.models.ResNet50_Weights.IMAGENET1K_V2)
        m.fc = nn.Identity()
        self.model, self.device = m.to(device).eval(), device

    @torch.no_grad()
    def frames(self, frames, bs=128):
        out = []
        for i in range(0, len(frames), bs):
            x = _to_tensor(frames[i:i + bs], IMNET_MEAN, IMNET_STD, self.device)
            with torch.autocast("cuda", enabled=self.device != "cpu"):
                out.append(self.model(x).float().cpu())
        return torch.cat(out).numpy() if out else np.zeros((0, self.dim), np.float32)


class XClipEncoder:
    """Video encoder: 8-frame windows (4 s at 2 fps), one window per second; each frame gets
    the embedding of the window centred on it."""
    name, dim = "xclip", 512

    def __init__(self, device):
        from transformers import XCLIPModel
        self.model = XCLIPModel.from_pretrained("microsoft/xclip-base-patch32").to(device).eval()
        self.device = device

    @torch.no_grad()
    def frames(self, frames, win=8, stride=2, bs=8):
        T = len(frames)
        if T == 0:
            return np.zeros((0, self.dim), np.float32)
        centres = list(range(0, T, stride))
        idx = [np.clip(np.arange(c - win // 2, c + win // 2), 0, T - 1) for c in centres]
        embs = []
        for i in range(0, len(idx), bs):
            clips = np.stack([frames[j] for j in idx[i:i + bs]])          # [B,8,H,W,3]
            B = clips.shape[0]
            x = _to_tensor(clips.reshape(-1, *clips.shape[2:]), CLIP_MEAN, CLIP_STD, self.device)
            x = x.view(B, win, 3, x.shape[-2], x.shape[-1])
            with torch.autocast("cuda", enabled=self.device != "cpu"):
                e = self.model.get_video_features(pixel_values=x)
            if not torch.is_tensor(e):          # newer transformers return an output object
                e = e.pooler_output if getattr(e, "pooler_output", None) is not None else e[0]
            if e.dim() == 3:                    # [B, tokens, D] -> [B, D]
                e = e.mean(1)
            embs.append(F.normalize(e.float(), dim=-1).cpu())
        E = torch.cat(embs).numpy()
        return np.repeat(E, stride, axis=0)[:T]


ENCODERS = {"clip": ClipEncoder, "resnet": ResNetEncoder, "xclip": XClipEncoder}


# ---------------------------------------------------------------- models
class DilatedResidual(nn.Module):
    def __init__(self, dilation, ch, p=0.3):
        super().__init__()
        self.c1 = nn.Conv1d(ch, ch, 3, padding=dilation, dilation=dilation)
        self.c2 = nn.Conv1d(ch, ch, 1)
        self.dp = nn.Dropout(p)

    def forward(self, x):
        return x + self.dp(self.c2(F.relu(self.c1(x))))


class TCNStage(nn.Module):
    def __init__(self, din, ch, layers):
        super().__init__()
        self.inp = nn.Conv1d(din, ch, 1)
        self.layers = nn.ModuleList([DilatedResidual(2 ** i, ch) for i in range(layers)])

    def forward(self, x):                      # x [B, D, T]
        x = self.inp(x)
        for l in self.layers:
            x = l(x)
        return x


class CosineHeads(nn.Module):
    """One weight matrix per task; logits = scale * cos(embedding, class vector)."""

    def __init__(self, emb, ncls, init=None):
        super().__init__()
        self.W = nn.ParameterDict()
        for t, n in ncls.items():
            w = torch.as_tensor(init[t]).float().clone() if init and t in init else torch.randn(n, emb) * 0.02
            self.W[t] = nn.Parameter(w)
        self.logscale = nn.Parameter(torch.tensor(math.log(15.0)))

    def add_task(self, task, weights):
        self.W[task] = nn.Parameter(torch.as_tensor(weights).float().clone().to(self.logscale.device))

    def forward(self, z, task):
        return self.logscale.exp() * z @ F.normalize(self.W[task], dim=-1).t()


class StepTCN(nn.Module):
    """Main model. When the input is CLIP (din == emb) the embedding starts as the CLIP frame
    feature itself (residual, zero-initialised projection), so text-initialised heads give
    zero-shot predictions before any training."""

    def __init__(self, din, ncls, emb=512, ch=128, layers=6, stages=2, text_init=None):
        super().__init__()
        self.cfg = dict(din=din, ncls=ncls, emb=emb, ch=ch, layers=layers, stages=stages)
        self.residual = din == emb
        self.drop = nn.Dropout(0.2)
        self.stages = nn.ModuleList([TCNStage(din, ch, layers)] +
                                    [TCNStage(ch, ch, layers) for _ in range(stages - 1)])
        self.proj = nn.ModuleList([nn.Conv1d(ch, emb, 1) for _ in range(stages)])
        if self.residual:
            for p in self.proj:
                nn.init.zeros_(p.weight); nn.init.zeros_(p.bias)
        self.heads = CosineHeads(emb, ncls, text_init)

    def embed_all(self, x):                    # x [B, T, D] -> list of [B, T, E]
        base = x.transpose(1, 2)
        h = self.drop(base)
        zs = []
        for st, pr in zip(self.stages, self.proj):
            h = st(h)
            z = pr(h) + (base if self.residual else 0)
            zs.append(F.normalize(z.transpose(1, 2), dim=-1))
        return zs

    def embed(self, x):
        return self.embed_all(x)[-1]

    def forward(self, x, task):
        return [self.heads(z, task) for z in self.embed_all(x)]


class BiLSTMNet(nn.Module):
    """Baseline (professor's CNN-RNN): frame features -> 2-layer BiLSTM -> linear head per task."""

    def __init__(self, din, ncls, hid=256):
        super().__init__()
        self.cfg = dict(din=din, ncls=ncls, hid=hid)
        self.drop = nn.Dropout(0.2)
        self.lstm = nn.LSTM(din, hid, num_layers=2, batch_first=True, bidirectional=True, dropout=0.3)
        self.heads = nn.ModuleDict({t: nn.Linear(2 * hid, n) for t, n in ncls.items()})

    def forward(self, x, task):
        h, _ = self.lstm(self.drop(x))
        return [self.heads[task](h)]


class LinearNet(nn.Module):
    """Baseline for video-encoder features: per-frame linear head per task."""

    def __init__(self, din, ncls):
        super().__init__()
        self.cfg = dict(din=din, ncls=ncls)
        self.drop = nn.Dropout(0.2)
        self.heads = nn.ModuleDict({t: nn.Linear(din, n) for t, n in ncls.items()})

    def forward(self, x, task):
        return [self.heads[task](self.drop(x))]


def build_model(kind, din, ncls, text_init=None):
    if kind == "tcn":
        return StepTCN(din, ncls, text_init=text_init)
    if kind == "bilstm":
        return BiLSTMNet(din, ncls)
    if kind == "linear":
        return LinearNet(din, ncls)
    raise ValueError(kind)


# ---------------------------------------------------------------- inference (used by the backend)
class StepRecognizer:
    """Load an exported bundle and turn a video into timed steps.

    rec = StepRecognizer('kaushaldub_model'); rec.predict('video.mp4', 'PerformCPR')"""

    def __init__(self, bundle_dir, device=None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        cfg = json.load(open(os.path.join(bundle_dir, "config.json")))
        self.cfg = cfg
        m = cfg["model"]
        self.model = StepTCN(m["din"], {t: len(v) for t, v in cfg["vocab"].items()}, m["emb"], m["ch"],
                             m["layers"], m["stages"])
        self.model.load_state_dict(torch.load(os.path.join(bundle_dir, "model.pt"), map_location="cpu"))
        self.model.to(self.device).eval()
        self._enc = None

    @property
    def encoder(self):
        if self._enc is None:
            self._enc = ClipEncoder(self.device)
        return self._enc

    def tasks(self):
        return list(self.cfg["vocab"].keys())

    @torch.no_grad()
    def predict_features(self, feats, task):
        x = torch.from_numpy(np.asarray(feats, np.float32))[None].to(self.device)
        logits = self.model(x, task)[-1][0].float().cpu().numpy()
        return softmax(logits, self.cfg["temperature"].get(task, 1.0))

    def predict(self, video_path, task):
        fps = self.cfg["fps"]
        frames = read_frames(video_path, fps, 224, self.cfg["max_frames"])
        probs = self.predict_features(self.encoder.frames(frames), task)
        return self.format(probs, task)

    def format(self, probs, task):
        fps, vocab = self.cfg["fps"], self.cfg["vocab"][task]
        _, segs = decode(probs, max(1, int(round(self.cfg["min_len_s"] * fps))))
        steps = []
        for s in segs:
            if s["label"] == 0:
                continue
            steps.append({"idx": len(steps) + 1, "label": vocab[s["label"]],
                          "start": round(s["start"] / fps, 2), "end": round(s["end"] / fps, 2),
                          "confidence": round(s["confidence"], 3),
                          "low_confidence": s["confidence"] < self.cfg["low_conf"],
                          "keyframe_s": round((s["start"] + s["end"]) / 2 / fps, 2)})
        return {"task": task, "duration_s": round(len(probs) / fps, 2), "steps": steps}
