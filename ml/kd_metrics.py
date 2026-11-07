"""KaushalDub: decoding and evaluation helpers (numpy only, no torch).

Labels are integer arrays, one entry per sampled frame (FPS frames per second).
Class 0 is always "background" (no step happening)."""
import numpy as np

BG = 0


def softmax(logits, T=1.0):
    z = logits / T
    z = z - z.max(-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(-1, keepdims=True)


def to_segments(labels):
    """[0,0,2,2,2,1] -> [(0,0,2),(2,2,5),(1,5,6)] as (label, start, end) with end exclusive."""
    labels = np.asarray(labels)
    if len(labels) == 0:
        return []
    cut = np.flatnonzero(np.diff(labels)) + 1
    starts = np.r_[0, cut]
    ends = np.r_[cut, len(labels)]
    return [(int(labels[s]), int(s), int(e)) for s, e in zip(starts, ends)]


def smooth(labels, min_len):
    """Remove flicker: any segment shorter than min_len frames takes the label of its
    longer neighbour. Repeats until stable. Keeps the order of steps as they occur."""
    lab = np.asarray(labels).copy()
    if min_len <= 1 or len(lab) == 0:
        return lab
    for _ in range(len(lab)):
        segs = to_segments(lab)
        if len(segs) <= 1:
            break
        short = [i for i, (_, s, e) in enumerate(segs) if e - s < min_len]
        if not short:
            break
        # shortest first; on ties fix interior segments before the ones at the video edges
        i = min(short, key=lambda k: (segs[k][2] - segs[k][1], k == 0 or k == len(segs) - 1))
        prev = segs[i - 1] if i > 0 else None
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        if prev is None:
            new = nxt[0]
        elif nxt is None:
            new = prev[0]
        else:
            new = prev[0] if (prev[2] - prev[1]) >= (nxt[2] - nxt[1]) else nxt[0]
        lab[segs[i][1]:segs[i][2]] = new
    return lab


def decode(probs, min_len):
    """probs [T,C] -> smoothed labels and per-segment confidence list."""
    lab = smooth(probs.argmax(-1), min_len)
    segs = []
    for c, s, e in to_segments(lab):
        segs.append({"label": c, "start": s, "end": e, "confidence": float(probs[s:e, c].mean())})
    return lab, segs


def macro_f1(pred, gt, n_classes):
    """Frame-level macro F1 over classes that occur in gt or pred."""
    pred, gt = np.asarray(pred), np.asarray(gt)
    f1s = []
    for c in range(n_classes):
        tp = np.sum((pred == c) & (gt == c))
        fp = np.sum((pred == c) & (gt != c))
        fn = np.sum((pred != c) & (gt == c))
        if tp + fp + fn == 0:
            continue
        f1s.append(2 * tp / (2 * tp + fp + fn))
    return float(np.mean(f1s)) if f1s else 0.0


def f1_at_iou(pred, gt, iou=0.5, bg=BG):
    """Segmental F1@IoU (MS-TCN convention), background segments ignored."""
    P = [s for s in to_segments(pred) if s[0] != bg]
    G = [s for s in to_segments(gt) if s[0] != bg]
    if not P and not G:
        return 1.0
    if not P or not G:
        return 0.0
    used = [False] * len(G)
    tp = 0
    for c, s, e in P:
        best, bj = 0.0, -1
        for j, (gc, gs, ge) in enumerate(G):
            if gc != c or used[j]:
                continue
            inter = max(0, min(e, ge) - max(s, gs))
            union = max(e, ge) - min(s, gs)
            if inter / union > best:
                best, bj = inter / union, j
        if best >= iou:
            tp += 1
            used[bj] = True
    fp = len(P) - tp
    fn = len(G) - tp
    return 2 * tp / (2 * tp + fp + fn)


def edit_score(pred, gt, bg=BG):
    """Order metric: 100 * (1 - normalised Levenshtein distance) between the sequences
    of step labels (background removed). 100 = same steps in the same order."""
    a = [s[0] for s in to_segments(pred) if s[0] != bg]
    b = [s[0] for s in to_segments(gt) if s[0] != bg]
    if not a and not b:
        return 100.0
    d = np.zeros((len(a) + 1, len(b) + 1))
    d[:, 0] = np.arange(len(a) + 1)
    d[0, :] = np.arange(len(b) + 1)
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (a[i - 1] != b[j - 1]))
    return float(100 * (1 - d[-1, -1] / max(len(a), len(b))))


def boundary_f1(pred, gt, tol):
    """F1 of step boundaries: a predicted boundary is correct if within tol frames of an
    unmatched true boundary."""
    pb = np.flatnonzero(np.diff(np.asarray(pred))) + 1
    gb = np.flatnonzero(np.diff(np.asarray(gt))) + 1
    if len(pb) == 0 and len(gb) == 0:
        return 1.0
    if len(pb) == 0 or len(gb) == 0:
        return 0.0
    used = np.zeros(len(gb), bool)
    tp = 0
    for p in pb:
        d = np.abs(gb - p).astype(float)
        d[used] = np.inf
        j = int(np.argmin(d))
        if d[j] <= tol:
            used[j] = True
            tp += 1
    return 2 * tp / (len(pb) + len(gb))


def ece(probs, gt, bins=15):
    """Expected calibration error of the top-class confidence."""
    return ece_from(probs.max(-1), probs.argmax(-1) == gt, bins)


def ece_from(conf, correct, bins=15):
    edges = np.linspace(0, 1, bins + 1)
    e = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            e += m.mean() * abs(conf[m].mean() - correct[m].mean())
    return float(e)


def fit_temperature(logits, gt):
    """Single temperature T that minimises NLL on validation frames (temperature scaling)."""
    from scipy.optimize import minimize_scalar
    gt = np.asarray(gt)

    def nll(logT):
        p = softmax(logits, np.exp(logT))
        return -np.mean(np.log(p[np.arange(len(gt)), gt] + 1e-12))

    r = minimize_scalar(nll, bounds=(np.log(0.05), np.log(20)), method="bounded")
    return float(np.exp(r.x))


def evaluate(videos, fps, min_len_s=2.0, tol_s=2.0):
    """videos: list of dicts with 'probs' [T,C], 'gt' [T], 'n_classes'.
    Returns averaged metrics (percent)."""
    ml = max(1, int(round(min_len_s * fps)))
    tol = tol_s * fps
    rows = []
    allp, allg, allpr = [], [], []
    for v in videos:
        lab, _ = decode(v["probs"], ml)
        g = v["gt"]
        rows.append({
            "acc": float(np.mean(lab == g)),
            "f1@50": f1_at_iou(lab, g, 0.5),
            "edit": edit_score(lab, g) / 100,
            "bf1@2s": boundary_f1(lab, g, tol),
        })
        allp.append(lab); allg.append(g)
        allpr.append((v["probs"].max(-1), v["probs"].argmax(-1) == g))
    out = {k: 100 * float(np.mean([r[k] for r in rows])) for k in rows[0]} if rows else {}
    if rows:
        n = videos[0]["n_classes"]
        out["macro_f1"] = 100 * macro_f1(np.concatenate(allp), np.concatenate(allg), n)
        out["ece"] = 100 * ece_from(np.concatenate([c for c, _ in allpr]), np.concatenate([k for _, k in allpr]))
        out["videos"] = len(rows)
    return out
