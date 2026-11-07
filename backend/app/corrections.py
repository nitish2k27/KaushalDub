"""Annotator corrections: diff model vs annotator timelines, apply only the approved changes, and feed the
correction memory. Segments are dicts {label, start, end[, confidence]}; "background" = no step."""
from . import ml_adapter
from .db import get_store, now_iso

TOL = 0.25


def fill_background(segs, duration):
    """Cover [0, duration] completely: gaps between steps become background segments."""
    out, t = [], 0.0
    for s in sorted(segs, key=lambda x: x["start"]):
        if s["start"] - t > TOL:
            out.append({"label": "background", "start": round(t, 2), "end": round(s["start"], 2), "confidence": None})
        out.append(dict(s))
        t = max(t, s["end"])
    if duration and duration - t > TOL:
        out.append({"label": "background", "start": round(t, 2), "end": round(duration, 2), "confidence": None})
    return out


def model_at(model, t):
    return next((m for m in model if m["start"] <= t < m["end"]), None)


def compute_changes(model, ann):
    out = []
    for i, g in enumerate(ann):
        m = model_at(model, (g["start"] + g["end"]) / 2)
        frm = m["label"] if m else "background"
        moved = not any(abs(x["start"] - g["start"]) <= TOL and abs(x["end"] - g["end"]) <= TOL for x in model)
        relabel = g["label"] != frm
        if relabel or moved:
            out.append({"id": i, "start": g["start"], "end": g["end"], "label": g["label"], "from": frm,
                        "confidence": m.get("confidence") if m else None,
                        "kind": "both" if relabel and moved else ("label" if relabel else "boundary")})
    return out


def _clip(model, a, b):
    pieces, t = [], a
    for m in sorted(model, key=lambda x: x["start"]):
        s, e = max(a, m["start"]), min(b, m["end"])
        if e - s <= 1e-6:
            continue
        if s - t > 1e-6:
            pieces.append({"label": "background", "start": t, "end": s, "confidence": None})
        pieces.append({"label": m["label"], "start": s, "end": e, "confidence": m.get("confidence")})
        t = e
    if b - t > 1e-6:
        pieces.append({"label": "background", "start": t, "end": b, "confidence": None})
    return pieces


def apply_changes(model, ann, approved_ids):
    changed = {c["id"] for c in compute_changes(model, ann)}
    approved = set(approved_ids)
    pieces = []
    for i, g in enumerate(ann):
        if i not in changed:
            m = model_at(model, (g["start"] + g["end"]) / 2)
            pieces.append({**g, "confidence": (m or {}).get("confidence")})
        elif i in approved:
            pieces.append({**g, "confidence": 1.0, "human": True})
        else:
            pieces += _clip(model, g["start"], g["end"])
    merged = []
    for p in pieces:
        if merged and merged[-1]["label"] == p["label"] and abs(merged[-1]["end"] - p["start"]) <= TOL:
            merged[-1]["end"] = p["end"]
            merged[-1]["human"] = merged[-1].get("human") or p.get("human")
        else:
            merged.append(dict(p))
    return [m for m in merged if m["label"] != "background" and m["end"] - m["start"] > 0.2]


def rebuild_steps(video, new_segs):
    """Replace the video's steps by the corrected timeline, keeping the text of steps that did not change.
    Returns True if any step's text or timing changed (so narration must be re-rendered)."""
    db = get_store()
    old = sorted(db.select("steps", {"video_id": video["id"]}), key=lambda s: s["idx"])

    def overlap(a, s):
        return max(0.0, min(a["end"], s["end_s"]) - max(a["start"], s["start_s"]))

    used, rows, changed = set(), [], False
    for i, seg in enumerate(new_segs, 1):
        cand = [s for s in old if s["label"] == seg["label"] and s["id"] not in used
                and overlap(seg, s) >= 0.5 * min(seg["end"] - seg["start"], s["end_s"] - s["start_s"])]
        keep = max(cand, key=lambda s: overlap(seg, s)) if cand else None
        if keep:
            used.add(keep["id"])
            if abs(keep["start_s"] - seg["start"]) > TOL or abs(keep["end_s"] - seg["end"]) > TOL or keep["idx"] != i:
                changed = True
            rows.append({**keep, "idx": i, "start_s": round(seg["start"], 2), "end_s": round(seg["end"], 2),
                         "low_conf": False if seg.get("human") else keep["low_conf"]})
        else:
            changed = True
            label = seg["label"].strip().rstrip(".")
            sent = label[0].upper() + label[1:] + "."
            rows.append({"video_id": video["id"], "idx": i, "start_s": round(seg["start"], 2), "end_s": round(seg["end"], 2),
                         "label": seg["label"], "confidence": seg.get("confidence") or 1.0, "low_conf": False,
                         "title": label.title()[:40], "instruction": sent, "narration_en": sent, "edited": False,
                         "needs_review": True})
    if len(used) != len(old):
        changed = True
    for s in old:
        if s["id"] not in used:
            db.delete("steps", {"id": s["id"]})
            db.delete("translations", {"step_id": s["id"]})
    for r in rows:
        if r.get("id"):
            db.update("steps", {"id": r["id"]}, {k: v for k, v in r.items() if k != "id"})
        else:
            db.insert("steps", r)
    return changed


def add_to_memory(video, request_id, approved_changes, tmp):
    """Store CLIP features of each approved corrected segment (not background) in the skill's memory."""
    db = get_store()
    feat = video.get("features")
    if not feat:
        return 0
    feats = ml_adapter.load_npy("outputs", feat["path"], tmp)
    n = 0
    for c in approved_changes:
        if c["label"] == "background":
            continue
        arr = ml_adapter.segment_features(feats, feat["fps"], c["start"], c["end"])
        if not len(arr):
            continue
        path = ml_adapter.write_segment(f"memory/{video['task']}/{request_id}_{c['id']}.npy", arr)
        db.insert("correction_memory", {"task": video["task"], "label": c["label"], "feature_path": path,
                                        "source_request_id": request_id, "video_id": video["id"],
                                        "start_s": c["start"], "end_s": c["end"], "used_in_version": None,
                                        "created_at": now_iso()})
        n += 1
    return n
