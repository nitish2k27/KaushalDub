import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmt, labelName } from "@/lib/format";
import type { Segment } from "@/lib/types";
import { Icon } from "@/components/Icon";
import { TimelineBar } from "@/components/bits";
import { Player, type PlayerHandle } from "@/components/Player";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card, ErrorBox, Label as FieldLabel, Loading, Pill } from "@/components/ui/primitives";

interface Clip {
  clip_id: string; title: string; task: string; duration_s: number; source_url: string | null; vocab: string[];
  model_segments: Segment[]; annotation: { segments: Segment[]; status: string; reviewer_note?: string | null } | null;
  transcript: { start: number; end: number; text: string }[];
}

export default function LabelPage() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["clip", id], queryFn: () => api<Clip>(`/annotations/${id}`) });
  if (q.isLoading) return <Loading />;
  if (q.error || !q.data) return <ErrorBox error={q.error || "Clip not found"} />;
  return <Labeller clip={q.data} />;
}

function Labeller({ clip }: { clip: Clip }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const player = useRef<PlayerHandle>(null);
  const start = clip.annotation && clip.annotation.status !== "submitted" ? clip.annotation.segments : clip.model_segments.map((s) => ({ ...s, accepted: false }));
  const [segs, setSegs] = useState<Segment[]>(start);
  const [sel, setSel] = useState(() => Math.max(0, start.findIndex((s) => (s.confidence ?? 1) < 0.6)));
  const [t, setT] = useState(0);
  const [saved, setSaved] = useState(true);
  const [busy, setBusy] = useState(false);
  const first = useRef(true);
  const dur = clip.duration_s || segs.at(-1)?.end || 0;
  const g = segs[sel];
  const model = (s: Segment) => clip.model_segments.find((m) => m.start <= (s.start + s.end) / 2 && (s.start + s.end) / 2 < m.end);

  useEffect(() => {
    if (first.current) { first.current = false; return; }
    setSaved(false);
    const id = setTimeout(async () => {
      try { await api(`/annotations/${clip.clip_id}`, { method: "PUT", body: { segments: segs } }); setSaved(true); } catch { /* shown on submit */ }
    }, 800);
    return () => clearTimeout(id);
  }, [segs, clip.clip_id]);

  const update = (i: number, patch: Partial<Segment>) => setSegs(segs.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const pick = (i: number) => { setSel(i); player.current?.seek(segs[i].start + 0.05); };
  const split = () => {
    const at = Math.round((player.current?.time() ?? 0) * 10) / 10;
    if (at <= g.start + 0.5 || at >= g.end - 0.5) { toast("Move the playhead inside the selected segment first"); return; }
    setSegs([...segs.slice(0, sel), { ...g, end: at, accepted: false }, { ...g, start: at, accepted: false }, ...segs.slice(sel + 1)]);
  };
  const merge = () => {
    const b = segs[sel + 1];
    setSegs([...segs.slice(0, sel), { ...g, end: b.end, accepted: false }, ...segs.slice(sel + 2)]);
  };
  const accept = () => { update(sel, { accepted: true }); if (sel < segs.length - 1) pick(sel + 1); };
  const unclear = () => { update(sel, { label: "background", unclear: true, accepted: true }); toast("Marked unclear. The trainer will look at it."); };
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api<{ changes: number }>(`/annotations/${clip.clip_id}/submit`, { body: { segments: segs } });
      toast(r.changes ? `Sent ${r.changes} change${r.changes > 1 ? "s" : ""} to the trainer for approval` : "Submitted: you agree with the model");
      qc.invalidateQueries({ queryKey: ["annqueue"] });
      nav("/a/history");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not submit");
      setBusy(false);
    }
  };

  const m = g ? model(g) : undefined;
  const conf = m?.confidence ?? g?.confidence;
  const speech = g ? clip.transcript.filter((s) => s.end > g.start && s.start < g.end).map((s) => s.text).join(" ") : "";
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <Link className="btn sm" to="/a">← Queue</Link>
        <div className="grow"><h2>{clip.title}</h2><span className="tiny muted">{saved ? "Draft saved" : "Saving…"}</span></div>
        <Button variant="primary" disabled={busy} onClick={submit}>Submit labels</Button>
      </div>
      {clip.annotation?.status === "sent_back" && clip.annotation.reviewer_note && (
        <div className="banner" style={{ marginBottom: 12 }}><Icon name="flag" /><span className="small grow">Trainer’s note: {clip.annotation.reviewer_note}</span></div>
      )}
      <div className="grid2">
        <div className="stack">
          <Player ref={player} src={clip.source_url} lang="en" badge="Labelling view" onTime={(x) => setT(x)} durationHint={clip.duration_s} />
          <Card className="stack" style={{ gap: 10 }}>
            <div className="row"><b className="small">Segments</b><span className="grow" /><span className="tiny muted">Click a segment to select it</span></div>
            <TimelineBar segs={segs} duration={dur} onPick={pick} sel={sel} head={t} />
          </Card>
        </div>
        <div className="stack">
          {g && (
            <Card className="stack" style={{ gap: 12 }}>
              <div className="row"><h3>Segment {sel + 1}</h3><span className="tiny muted">{fmt(g.start)}–{fmt(g.end)}</span><span className="grow" />
                {g.accepted ? <Pill tone="good">Accepted</Pill> : conf == null ? <Pill tone="gray">No step</Pill>
                  : conf < 0.6 ? <Pill tone="warn">Low confidence {conf.toFixed(2)}</Pill> : <Pill tone="gray">Model {conf.toFixed(2)}</Pill>}</div>
              <div><FieldLabel htmlFor="lab">Step label</FieldLabel>
                <select id="lab" value={g.label} onChange={(e) => update(sel, { label: e.target.value, accepted: true, unclear: false })}>
                  {clip.vocab.map((v) => <option key={v} value={v}>{labelName(v)}</option>)}
                </select></div>
              <div className="row">
                <Button size="sm" onClick={() => player.current?.playRange(g.start, g.end)}><Icon name="play" />Play segment</Button>
                <Button size="sm" onClick={split}><Icon name="split" />Split at playhead</Button>
                <Button size="sm" disabled={sel >= segs.length - 1} onClick={merge}>Merge with next</Button>
              </div>
              <div className="row">
                <Button size="sm" variant="primary" onClick={accept}><Icon name="check" />Accept</Button>
                <Button size="sm" onClick={unclear}><Icon name="flag" />Mark unclear</Button>
              </div>
              {speech && <p className="small muted">Speech here: “{speech.slice(0, 220)}”</p>}
              {conf != null && conf < 0.6 && !g.accepted && <p className="small" style={{ color: "var(--accent)" }}>The model was unsure about this segment. Watch it and pick the right label.</p>}
            </Card>
          )}
          <Card>
            <b className="small">Label vocabulary</b>
            <div className="chips" style={{ marginTop: 8 }}>{clip.vocab.map((v) => <Pill key={v} tone="gray">{labelName(v)}</Pill>)}</div>
            <p className="tiny muted" style={{ marginTop: 8 }}>{segs.filter((x) => x.accepted).length} of {segs.length} segments accepted</p>
          </Card>
        </div>
      </div>
    </>
  );
}
