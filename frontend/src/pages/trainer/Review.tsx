import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useVideo } from "@/lib/hooks";
import { fmt, LNE } from "@/lib/format";
import type { QuizItem, Step, Video } from "@/lib/types";
import { Icon } from "@/components/Icon";
import { LangBar, Pipe } from "@/components/bits";
import { captionFromSteps, Player, type PlayerHandle } from "@/components/Player";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card, Chip, ErrorBox, Input, Loading, Pill, Textarea } from "@/components/ui/primitives";

type Draft = Pick<Step, "title" | "instruction" | "narration_en">;

export default function Review() {
  const { id } = useParams();
  const v = useVideo(id);
  if (v.isLoading) return <Loading />;
  if (v.error || !v.data) return <ErrorBox error={v.error || "Video not found"} />;
  return <ReviewBody video={v.data} />;
}

function ReviewBody({ video }: { video: Video }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const player = useRef<PlayerHandle>(null);
  const [tab, setTab] = useState<"steps" | "quiz">("steps");
  const [lang, setLang] = useState("en");
  const [active, setActive] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"steps" | "full">(video.dub_mode || "steps");
  const [err, setErr] = useState<unknown>(null);
  const steps = video.steps || [];

  const merged: Step[] = steps.map((s) => (drafts[s.id] ? { ...s, ...drafts[s.id], texts: { ...s.texts, en: drafts[s.id].narration_en } } : s));
  const dirty = (s: Step) => {
    const d = drafts[s.id];
    return !!d && (d.title !== s.title || d.instruction !== s.instruction || d.narration_en !== s.narration_en);
  };

  const save = async (s: Step) => {
    if (!dirty(s)) return;
    setSaving(s.id);
    try {
      const fresh = await api<Video>(`/videos/${video.id}/steps`, { method: "PATCH", body: { steps: [{ id: s.id, ...drafts[s.id] }] } });
      qc.setQueryData(["video", video.id], fresh);
      setDrafts(({ [s.id]: _, ...rest }) => rest);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(null);
    }
  };

  const edit = (s: Step, field: keyof Draft, value: string) =>
    setDrafts((d) => {
      const base: Draft = d[s.id] ?? { title: s.title, instruction: s.instruction, narration_en: s.narration_en };
      return { ...d, [s.id]: { ...base, [field]: value } };
    });

  const approve = async () => {
    setBusy(true);
    setErr(null);
    try {
      for (const s of steps) if (dirty(s)) await save(s);
      await api(`/videos/${video.id}/approve`, { method: "POST", query: { mode } });
      qc.invalidateQueries({ queryKey: ["video", video.id] });
      nav(`/t/videos/${video.id}/dub`);
    } catch (e) {
      setErr(e);
      setBusy(false);
    }
  };

  const lowCount = steps.filter((s) => s.low_conf).length;
  const langs = video.langs;
  const dubbed = video.outputs && Object.keys(video.outputs).length > 1;
  return (
    <>
      <Pipe n={2} />
      <div className="row" style={{ marginBottom: 14 }}>
        <div className="grow"><h2>Review steps and captions</h2><p className="muted small">Edit anything that is wrong. Step order follows the video timeline.</p></div>
        {video.order_ok ? <Pill tone="good"><Icon name="check" />Order check passed</Pill> : <Pill tone="bad">Check step times</Pill>}
        <label className="small" htmlFor="dubmode" style={{ display: "flex", alignItems: "center", gap: 6 }}>Narration
          <select id="dubmode" value={mode} onChange={(e) => setMode(e.target.value as "steps" | "full")} style={{ width: "auto", minHeight: 40 }}>
            <option value="steps">Step narration (~₹4)</option>
            <option value="full">Full speech translation (~₹10–20)</option>
          </select>
        </label>
        <Button variant="primary" onClick={approve} disabled={busy || !steps.length}>{busy ? "Starting…" : dubbed ? "Approve and re-make dub" : "Approve and create dub"}</Button>
      </div>
      <ErrorBox error={err} />
      {video.llm_fallback && (
        <div className="banner" style={{ marginBottom: 12 }}><Icon name="flag" /><span className="small grow">The LLM was not available, so the step text is a plain template from the step labels. Please rewrite it before approving.</span></div>
      )}
      <div className="grid2">
        <div className="stack">
          <Player ref={player} src={video.source_url} lang={lang} steps={merged} captionText={captionFromSteps(merged, lang)}
            badge="Original" onStep={setActive} durationHint={video.duration_s} />
          <Card>
            <b className="small">Caption language</b>
            <div style={{ marginTop: 8 }}><LangBar langs={langs} cur={lang} onPick={setLang} /></div>
            <p className="tiny muted" style={{ marginTop: 8 }}>
              {lang === "en" ? "Captions follow the step that is on screen."
                : dubbed ? `Showing the current ${LNE[lang]} text. Edit translations on the result page.`
                  : `${LNE[lang]} captions are made when you approve. You can still fix them afterwards.`}
            </p>
          </Card>
          {video.transcript && video.transcript.length > 0 && (
            <details className="card">
              <summary className="small" style={{ cursor: "pointer", fontWeight: 600, minHeight: 32 }}>What the instructor said ({video.spoken_lang})</summary>
              <div className="small muted" style={{ marginTop: 8, maxHeight: 220, overflow: "auto" }}>
                {video.transcript.map((t, i) => <p key={i}><span className="tiny">{fmt(t.start)}</span> {t.text}</p>)}
              </div>
            </details>
          )}
        </div>
        <div className="stack">
          <div className="chips">
            <Chip on={tab === "steps"} onClick={() => setTab("steps")}>Steps ({steps.length})</Chip>
            <Chip on={tab === "quiz"} onClick={() => setTab("quiz")}>Quiz</Chip>
          </div>
          {tab === "steps" ? (
            <div className="stack" style={{ gap: 10 }}>
              {lowCount > 0 && <p className="small" style={{ color: "var(--accent)" }}>{lowCount} step{lowCount > 1 ? "s" : ""} with low model confidence. Please check {lowCount > 1 ? "them" : "it"}.</p>}
              {merged.map((s) => (
                <div key={s.id} className={`edit ${s.low_conf ? "low" : ""} ${s.idx === active ? "on" : ""}`}>
                  <div className="row" style={{ marginBottom: 6 }}>
                    <b>{s.idx}.</b>
                    <Input aria-label={`Step ${s.idx} title`} value={s.title} onChange={(e) => edit(s, "title", e.target.value)} onBlur={() => save(steps.find((x) => x.id === s.id)!)}
                      style={{ flex: 1, minWidth: 120, minHeight: 36, padding: "4px 10px", fontWeight: 600 }} />
                    <span className="tiny muted">{fmt(s.start_s)}–{fmt(s.end_s)}</span>
                    {s.low_conf ? <Pill tone="warn">Low confidence {s.confidence.toFixed(2)}</Pill> : <Pill tone="gray">{s.confidence.toFixed(2)}</Pill>}
                    {s.needs_review && <Pill tone="warn">Changed by annotator</Pill>}
                    <Button size="sm" aria-label={`Play step ${s.idx}`} onClick={() => player.current?.seek(s.start_s + 0.05, true)}><Icon name="play" /></Button>
                  </div>
                  <span className="tiny muted">Detected: {s.label}</span>
                  <label className="l" style={{ marginTop: 6 }} htmlFor={`n${s.id}`}>Narration and caption (English)</label>
                  <Textarea id={`n${s.id}`} lang="en" value={s.narration_en} onChange={(e) => edit(s, "narration_en", e.target.value)} onBlur={() => save(steps.find((x) => x.id === s.id)!)} />
                  <label className="l" style={{ marginTop: 6 }} htmlFor={`i${s.id}`}>Instruction (step list)</label>
                  <Input id={`i${s.id}`} value={s.instruction} onChange={(e) => edit(s, "instruction", e.target.value)} onBlur={() => save(steps.find((x) => x.id === s.id)!)} />
                  {saving === s.id && <p className="tiny muted">Saving…</p>}
                  {s.low_conf && (
                    <>
                      <p className="tiny" style={{ marginTop: 6, color: "var(--accent)" }}>Model was unsure here. A keyframe was sent to the LLM; please check this step.</p>
                      {s.keyframe_url && <img className="kf" src={s.keyframe_url} alt={`Keyframe of step ${s.idx}`} />}
                    </>
                  )}
                </div>
              ))}
            </div>
          ) : <QuizEditor video={video} />}
        </div>
      </div>
    </>
  );
}

function QuizEditor({ video }: { video: Video }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [items, setItems] = useState<QuizItem[]>(video.quiz?.items || []);
  const [dirty, setDirty] = useState(false);
  useEffect(() => { setItems(video.quiz?.items || []); setDirty(false); }, [video.quiz]);
  const upd = (i: number, f: (q: QuizItem) => QuizItem) => { setItems(items.map((q, j) => (j === i ? f(q) : q))); setDirty(true); };
  const save = async () => {
    try {
      qc.setQueryData(["video", video.id], await api<Video>(`/videos/${video.id}/quiz`, { method: "PUT", body: { items } }));
      setDirty(false);
      toast("Quiz saved");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save the quiz");
    }
  };
  if (!video.quiz_enabled && !items.length) return <p className="muted small">Quiz was switched off for this video.</p>;
  return (
    <div className="stack" style={{ gap: 10 }}>
      {items.length === 0 && <p className="muted small">The LLM did not write a quiz. Add questions below.</p>}
      {items.map((q, i) => (
        <div key={i} className="edit qedit stack" style={{ gap: 6 }}>
          <div className="row"><b>Q{i + 1}.</b><Input aria-label={`Question ${i + 1}`} value={q.q} className="grow" style={{ flex: 1 }}
            onChange={(e) => upd(i, (x) => ({ ...x, q: e.target.value }))} />
            <Button size="sm" aria-label={`Delete question ${i + 1}`} onClick={() => { setItems(items.filter((_, j) => j !== i)); setDirty(true); }}>✕</Button></div>
          {q.options.map((o, j) => (
            <label key={j} className="row" style={{ gap: 8 }}>
              <input type="radio" name={`ans${i}`} checked={q.answer === j} onChange={() => upd(i, (x) => ({ ...x, answer: j }))} style={{ width: 20, height: 20 }}
                aria-label={`Option ${"ABCD"[j]} is correct`} />
              <span className="tiny" style={{ width: 14 }}>{"ABCD"[j]}</span>
              <Input value={o} style={{ flex: 1, color: q.answer === j ? "var(--good)" : undefined }} aria-label={`Question ${i + 1} option ${"ABCD"[j]}`}
                onChange={(e) => upd(i, (x) => ({ ...x, options: x.options.map((y, k) => (k === j ? e.target.value : y)) }))} />
            </label>
          ))}
        </div>
      ))}
      <div className="row">
        <Button size="sm" onClick={() => { setItems([...items, { q: "", options: ["", "", "", ""], answer: 0 }]); setDirty(true); }}>Add question</Button>
        <Button size="sm" variant="primary" disabled={!dirty} onClick={save}>Save quiz</Button>
      </div>
      <p className="tiny muted">The quiz is translated with the narration when you approve.</p>
    </div>
  );
}
