import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ago, fmt, labelName } from "@/lib/format";
import type { AnnRequest, Video } from "@/lib/types";
import { Icon } from "@/components/Icon";
import { TimelineBar } from "@/components/bits";
import { Player, type PlayerHandle } from "@/components/Player";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card, ErrorBox, Label, Loading, StatusPill, Textarea } from "@/components/ui/primitives";

type Detail = { request: AnnRequest; video: Video };

export default function AnnReview() {
  const { id } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const player = useRef<PlayerHandle>(null);
  const q = useQuery({ queryKey: ["annreq", id], queryFn: () => api<Detail>(`/annotation-requests/${id}`) });
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [t, setT] = useState(0);
  const r = q.data?.request;
  useEffect(() => {
    if (r) { setSel(new Set(r.status === "pending" ? r.changes.map((c) => c.id) : (r as AnnRequest & { approved_changes?: number[] }).approved_changes || [])); setNote(r.note || ""); }
  }, [r?.id, r?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  if (q.isLoading) return <Loading />;
  if (q.error || !r || !q.data) return <ErrorBox error={q.error || "Request not found"} />;
  const video = q.data.video;
  const pend = r.status === "pending";
  const dur = video.duration_s || r.model_segments?.at(-1)?.end || 0;

  const act = async (kind: "approve" | "send-back") => {
    setBusy(true);
    setErr(null);
    try {
      const out = await api<{ applied?: number; memory_added?: number; rerender_job?: string | null; retrain_job?: string | null }>(
        `/annotation-requests/${r.id}/${kind}`, { method: "POST", body: kind === "approve" ? { change_ids: [...sel], note } : { note } });
      toast(kind === "approve"
        ? `${out.applied} correction${out.applied === 1 ? "" : "s"} applied to the video and added to the model’s memory${out.rerender_job ? "; narration is being re-rendered" : ""}${out.retrain_job ? "; retraining started" : ""}`
        : "Sent back to the annotator");
      await q.refetch();
      qc.invalidateQueries({ queryKey: ["annreq"] });
      qc.invalidateQueries({ queryKey: ["model"] });
    } catch (e) {
      setErr(e);
    }
    setBusy(false);
  };

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <Link className="btn sm" to="/t/annotations">← Requests</Link>
        <div className="grow"><h2>{r.video_title}</h2><p className="muted small">Corrected by {r.annotator_name} · {ago(r.created_at)}</p></div>
        <StatusPill status={r.status} />
      </div>
      <ErrorBox error={err} />
      <div className="grid2">
        <div className="stack">
          <Player ref={player} src={video.source_url} lang="en" steps={video.steps} badge="Annotated clip" onTime={(x) => setT(x)} durationHint={video.duration_s} />
          <Card className="stack" style={{ gap: 8 }}>
            <TimelineBar segs={r.model_segments || []} label="Model suggestion" duration={dur} head={t} />
            <TimelineBar segs={r.annotator_segments || []} label="Annotator’s labels" duration={dur} head={t} />
          </Card>
        </div>
        <div className="stack">
          <Card className="stack" style={{ gap: 10 }}>
            <h3>{r.changes.length} change{r.changes.length === 1 ? "" : "s"} to review</h3>
            {r.changes.length ? r.changes.map((c) => (
              <label key={c.id} className="chg">
                <input type="checkbox" checked={sel.has(c.id)} disabled={!pend}
                  onChange={(e) => { const s = new Set(sel); e.target.checked ? s.add(c.id) : s.delete(c.id); setSel(s); }} />
                <span className="grow"><b>{fmt(c.start)}–{fmt(c.end)}</b> · {c.kind === "boundary" ? "Boundary moved" : <><span className="muted">{labelName(c.from)}</span> → <b>{labelName(c.label)}</b></>}
                  {c.kind === "both" && " (boundary moved too)"}<br />
                  <span className="tiny muted">Model confidence here: {c.confidence != null ? c.confidence.toFixed(2) : "no step"}</span></span>
                <Button size="sm" aria-label={`Play ${fmt(c.start)} to ${fmt(c.end)}`} onClick={(e) => { e.preventDefault(); player.current?.playRange(c.start, c.end); }}><Icon name="play" /></Button>
              </label>
            )) : <p className="muted small">No differences from the model.</p>}
            <Label htmlFor="rqnote">Note to the annotator (optional)</Label>
            <Textarea id="rqnote" value={note} disabled={!pend} onChange={(e) => setNote(e.target.value)} />
            <div className="row">
              <Button variant="primary" disabled={!pend || busy || sel.size === 0} onClick={() => act("approve")}><Icon name="check" />Approve selected changes</Button>
              <Button disabled={!pend || busy} onClick={() => act("send-back")}>Send back</Button>
            </div>
            <p className="tiny muted">Approving updates this video’s steps and adds the corrections to the model’s memory for this skill.</p>
          </Card>
        </div>
      </div>
    </>
  );
}
