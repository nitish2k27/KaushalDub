import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ago, fmt, LNE } from "@/lib/format";
import type { Ticket, Video } from "@/lib/types";
import { Icon } from "@/components/Icon";
import { captionFromSteps, Player, type PlayerHandle } from "@/components/Player";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card, ErrorBox, Label, Loading, StatusPill, Textarea } from "@/components/ui/primitives";
import { sourcesFor, waitForJob } from "./Result";

type Detail = { ticket: Ticket; video: Video };

export default function TicketPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const player = useRef<PlayerHandle>(null);
  const q = useQuery({ queryKey: ["ticket", id], queryFn: () => api<Detail>(`/tickets/${id}`) });
  const [text, setText] = useState("");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);

  const t = q.data?.ticket;
  const video = q.data?.video;
  const step = video?.steps?.find((s) => s.idx === t?.step_idx);
  useEffect(() => {
    if (t && step) setText(step.texts[t.lang] || step.narration_en);
    if (t) setReply(t.reply || "");
  }, [t?.id, step?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (q.isLoading) return <Loading />;
  if (q.error || !t || !video) return <ErrorBox error={q.error || "Report not found"} />;
  const open = t.status === "open";
  const { src, vtt } = sourcesFor(video, t.lang, true);
  const changed = step && text.trim() !== (step.texts[t.lang] || step.narration_en);
  const done = (d: Detail) => {
    qc.setQueryData(["ticket", id], d);
    qc.invalidateQueries({ queryKey: ["tickets"] });
  };

  const revoice = async () => {
    if (!step) return;
    setBusy("voice");
    setErr(null);
    try {
      if (changed) done(await api<Detail>(`/tickets/${t.id}`, { method: "PATCH", body: { text } }));
      const r = await api<{ job_id: string }>(`/videos/${video.id}/steps/${step.idx}/revoice`, { method: "POST", query: { lang: t.lang } });
      toast(`Re-making the voice for step ${step.idx}…`);
      const j = await waitForJob(r.job_id);
      if (j.status !== "done") throw new Error(j.error || "Re-voicing failed");
      await q.refetch();
      toast(`Voice re-made for step ${step.idx} in ${LNE[t.lang]}`);
    } catch (e) {
      setErr(e);
    }
    setBusy(null);
  };

  const close = async (status: "resolved" | "closed") => {
    setBusy(status);
    setErr(null);
    try {
      done(await api<Detail>(`/tickets/${t.id}`, { method: "PATCH",
        body: { status, reply: reply.trim() || undefined, ...(status === "resolved" && changed ? { text } : {}) } }));
      toast(status === "resolved" ? "Fix saved and report closed" : "Report closed");
    } catch (e) {
      setErr(e);
    }
    setBusy(null);
  };

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <Link className="btn sm" to="/t/reports">← Reports</Link>
        <div className="grow"><h2>Report · {t.video_title}</h2>
          <p className="muted small">{t.category} at {fmt(t.timestamp_s)} in the {LNE[t.lang]} version · from {t.reporter_name} · {ago(t.created_at)}</p></div>
        <StatusPill status={t.status} />
      </div>
      <ErrorBox error={err} />
      <div className="grid2">
        <div className="stack">
          <Player ref={player} src={src} vtt={vtt} lang={t.lang} steps={video.steps} captionText={captionFromSteps(video.steps, t.lang)}
            startAt={t.timestamp_s} badge={`Opened at ${fmt(t.timestamp_s)}`} durationHint={video.duration_s} />
          <Card><b className="small">Learner’s message</b><p style={{ marginTop: 6 }}>“{t.message}”</p></Card>
        </div>
        <div className="stack">
          <Card className="stack" style={{ gap: 10 }}>
            {step ? (
              <>
                <div className="row"><h3>Step {step.idx} · {step.title}</h3><span className="tiny muted">{fmt(step.start_s)}–{fmt(step.end_s)}</span></div>
                <Label htmlFor="fixtext">{LNE[t.lang]} narration and caption for this step</Label>
                <Textarea id="fixtext" lang={t.lang} value={text} disabled={!open} onChange={(e) => setText(e.target.value)} />
                <div className="row">
                  <Button size="sm" onClick={() => player.current?.seek(t.timestamp_s, true)}><Icon name="play" />Play from the reported moment</Button>
                  {t.lang !== "en" && <Button size="sm" disabled={!open || !!busy} onClick={revoice}>{busy === "voice" ? "Re-making…" : "Re-make voice for this step"}</Button>}
                </div>
              </>
            ) : <p className="muted small">The step at this moment no longer exists (the steps were changed since).</p>}
          </Card>
          <Card className="stack" style={{ gap: 10 }}>
            <Label htmlFor="tkreply">Reply to the learner</Label>
            <Textarea id="tkreply" placeholder="What you changed, or why no change is needed" value={reply} disabled={!open} onChange={(e) => setReply(e.target.value)} />
            <div className="row">
              <Button variant="primary" disabled={!open || !!busy} onClick={() => close("resolved")}><Icon name="check" />Save fix and close</Button>
              <Button disabled={!open || !!busy} onClick={() => close("closed")}>Close without change</Button>
            </div>
            {!open && <p className="tiny muted">Closed. The learner sees your reply in My progress.</p>}
          </Card>
        </div>
      </div>
    </>
  );
}
