import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { fmt, hue, labelName, LN } from "@/lib/format";
import type { Job, Segment, Step } from "@/lib/types";
import { Icon } from "./Icon";
import { Button } from "./ui/button";
import { Card, Chip, Progress } from "./ui/primitives";

const PIPE = ["Upload", "Process", "Review", "Dub", "Publish"];
export function Pipe({ n }: { n: number }) {
  return (
    <div className="pipe" aria-label={`Step ${Math.min(n + 1, 5)} of 5: ${PIPE[Math.min(n, 4)]}`}>
      {PIPE.map((p, i) => <span key={p} className={i === n ? "on" : i < n ? "done" : ""}>{i < n ? "✓ " : ""}{p}</span>)}
    </div>
  );
}

export function LangBar({ langs, cur, onPick, label = "Language" }: { langs: string[]; cur: string; onPick: (l: string) => void; label?: string }) {
  return (
    <div className="chips" role="group" aria-label={label}>
      {langs.map((l) => <Chip key={l} on={l === cur} onClick={() => onPick(l)} lang={l}>{LN[l] || l}</Chip>)}
    </div>
  );
}

export function StepList({ steps, lang, active, onPick }: { steps: Step[]; lang: string; active: number | null; onPick: (s: Step) => void }) {
  return (
    <>
      {steps.map((s) => (
        <button key={s.id} className={`step ${s.idx === active ? "on" : active !== null && s.idx < active ? "done" : ""}`} onClick={() => onPick(s)}>
          <span className="n">{s.idx}</span>
          <span><b>{s.title}</b> <span className="tiny muted">{fmt(s.start_s)}</span><br />
            <span className="small muted" lang={lang}>{s.texts[lang] || s.narration_en}</span></span>
        </button>
      ))}
    </>
  );
}

/** Polls a job and shows the mockup's stage list. */
export function JobProgress({ jobId, title, sub, onDone, onResume }: { jobId: string; title: string; sub?: string;
  onDone?: (j: Job) => void; onResume?: () => void }) {
  const q = useQuery({
    queryKey: ["job", jobId], queryFn: () => api<Job>(`/jobs/${jobId}`),
    refetchInterval: (query) => (["queued", "running"].includes(query.state.data?.status ?? "queued") ? 1500 : false),
  });
  const j = q.data;
  const done = useRef(false);
  useEffect(() => {
    if (j?.status === "done" && !done.current) {
      done.current = true;
      onDone?.(j);
    }
  }, [j, onDone]);
  return (
    <Card style={{ maxWidth: 640, margin: "0 auto" }}>
      <h2>{title}</h2>
      {sub && <p className="muted small" style={{ margin: "4px 0 16px" }}>{sub}</p>}
      <Progress value={j?.progress ?? 2} label="Progress" />
      <div style={{ marginTop: 8 }}>
        {(j?.stages?.length ? j.stages : [{ key: "q", label: "Waiting for a worker", status: "run" as const }]).map((s) => (
          <div key={s.key} className={`stage ${s.status === "run" ? "run" : s.status === "done" ? "done" : s.status === "failed" ? "fail" : "wait"}`}>
            <span className="dot">{s.status === "done" && <Icon name="check" />}{s.status === "failed" && "✕"}</span>
            <span className="grow">{s.label}</span>
            {s.provider && <span className="pill gray">{s.provider}</span>}
          </div>
        ))}
      </div>
      {j?.status === "queued" && j.queue === "gpu" && (
        <p className="small muted" style={{ marginTop: 8 }}>This job runs on the GPU worker (free local models). It starts when the worker notebook is online.</p>
      )}
      {j?.status === "needs_credits" && (
        <div className="banner" style={{ marginTop: 14 }} role="alert">
          <Icon name="flag" /><span className="grow small">{j.error}</span>
          <Link className="btn sm" to="/t/settings">Plan and keys</Link>
          {onResume && <Button size="sm" variant="primary" onClick={onResume}>Resume</Button>}
        </div>
      )}
      {j?.status === "failed" && (
        <div className="stack" style={{ marginTop: 14, gap: 8 }}>
          <div className="errbox small" role="alert">{j.error}</div>
          {onResume && <Button size="sm" onClick={onResume}><Icon name="redo" />Try again</Button>}
        </div>
      )}
      {j && j.logs?.length > 0 && (
        <details style={{ marginTop: 12 }}>
          <summary className="small muted" style={{ cursor: "pointer", minHeight: 32 }}>Details{j.cost?.inr ? ` · estimated cost ₹${j.cost.inr}` : ""}</summary>
          <div className="logs">{j.logs.slice(-40).map((l, i) => <div key={i} style={{ color: l.level === "error" ? "var(--bad)" : l.level === "warn" ? "var(--accent)" : undefined }}>{l.msg}</div>)}</div>
        </details>
      )}
    </Card>
  );
}

export function TimelineBar({ segs, label, duration, onPick, sel, head }: { segs: Segment[]; label?: string; duration: number;
  onPick?: (i: number) => void; sel?: number; head?: number }) {
  return (
    <>
      {label && <div className="tlab">{label}</div>}
      <div className="tl" style={{ height: onPick ? 52 : 40 }}>
        {segs.map((x, i) => {
          const style = { flex: Math.max(0.01, x.end - x.start), background: `hsl(${hue(x.label)} 50% 36%)` };
          const text = labelName(x.label);
          return onPick ? (
            <button key={i} className={`seg ${i === sel ? "sel" : ""}`} style={style} onClick={() => onPick(i)}
              aria-label={`Segment ${i + 1}: ${text}, ${fmt(x.start)} to ${fmt(x.end)}`} aria-pressed={i === sel}>
              {x.accepted ? "✓ " : ""}{text}
            </button>
          ) : <span key={i} className="seg" style={style} title={`${text} ${fmt(x.start)}–${fmt(x.end)}`}>{text}</span>;
        })}
        {head !== undefined && duration > 0 && <span className="head" style={{ left: `${(head / duration) * 100}%` }} />}
      </div>
    </>
  );
}
