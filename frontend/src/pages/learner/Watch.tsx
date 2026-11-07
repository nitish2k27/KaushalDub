import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import { useConfig, useVideo } from "@/lib/hooks";
import { fmt, LNE } from "@/lib/format";
import type { Video } from "@/lib/types";
import { Icon } from "@/components/Icon";
import { LangBar, StepList } from "@/components/bits";
import { captionFromSteps, Player, stepIdxAt, type PlayerHandle } from "@/components/Player";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card, Chip, ErrorBox, Label, Loading, Textarea } from "@/components/ui/primitives";
import { sourcesFor } from "../trainer/Result";

const LANG_KEY = "kd_lang";

export default function Watch() {
  const { id } = useParams();
  const v = useVideo(id);
  if (v.isLoading) return <Loading />;
  if (v.error || !v.data) return <ErrorBox error={v.error || "Video not found"} />;
  return <WatchBody video={v.data} />;
}

function WatchBody({ video }: { video: Video }) {
  const nav = useNavigate();
  const toast = useToast();
  const cfg = useConfig();
  const player = useRef<PlayerHandle>(null);
  const [lang, setLangState] = useState(() => {
    try { const l = localStorage.getItem(LANG_KEY); if (l && video.langs.includes(l)) return l; } catch { /* ignore */ }
    return video.langs.includes("kn") ? "kn" : video.langs[0];
  });
  const setLang = (l: string) => { setLangState(l); try { localStorage.setItem(LANG_KEY, l); } catch { /* ignore */ } };
  const [narr, setNarr] = useState(true);
  const [active, setActive] = useState<number | null>(null);
  const [rep, setRep] = useState<{ t: number; cat: string; msg: string } | null>(null);
  const [sending, setSending] = useState(false);
  const lastSent = useRef(0);
  const msgRef = useRef<HTMLTextAreaElement>(null);
  const steps = video.steps || [];
  const { src, vtt } = sourcesFor(video, lang, narr);
  const repStep = rep ? steps.find((s) => s.idx === stepIdxAt(steps, rep.t)) : null;

  useEffect(() => { if (rep) msgRef.current?.focus(); }, [rep !== null]); // eslint-disable-line react-hooks/exhaustive-deps

  const onTime = (t: number, d: number) => {
    if (!d || Date.now() - lastSent.current < 10000) return;
    lastSent.current = Date.now();
    void api(`/videos/${video.id}/progress`, { body: { progress: (t / d) * 100, lang } }).catch(() => {});
  };

  const send = async () => {
    if (!rep) return;
    if (!rep.msg.trim()) { toast("Add a short message so the trainer knows what to fix"); msgRef.current?.focus(); return; }
    setSending(true);
    try {
      await api(`/videos/${video.id}/tickets`, { body: { lang, timestamp_s: rep.t, category: rep.cat, message: rep.msg.trim() } });
      setRep(null);
      toast("Report sent to the trainer");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not send");
    }
    setSending(false);
  };

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <Link className="btn sm" to="/l">← Library</Link>
        <span className="grow" />
        <Button disabled={!!rep} onClick={() => { player.current?.pause(); setRep({ t: player.current?.time() ?? 0, cat: "Wrong step", msg: "" }); }}>
          <Icon name="flag" />Report a problem</Button>
        {video.quiz?.items.length ? <Button variant="primary" onClick={() => nav(`/l/quiz/${video.id}?lang=${lang}`)}>Take the quiz</Button> : null}
      </div>
      <div className="grid2">
        <div className="stack">
          <div><h2>{video.title}</h2><p className="muted small">{video.by} · {video.domain} · {video.task_title}</p></div>
          <Player ref={player} src={src} vtt={vtt} lang={lang} steps={steps} captionText={captionFromSteps(steps, lang)} onStep={setActive}
            onTime={onTime} durationHint={video.duration_s} label={video.title}
            narration={video.outputs?.[lang]?.dubbed ? { on: narr, toggle: () => setNarr(!narr) } : null} />
          {rep && (
            <Card className="stack" style={{ gap: 12, borderColor: "var(--accent)" }}>
              <div className="row"><h3>Report a problem</h3><span className="grow" /><Button size="sm" aria-label="Close the report form" onClick={() => setRep(null)}>✕</Button></div>
              <p className="small">At <b>{fmt(rep.t)}</b> · {repStep ? `Step ${repStep.idx} · ${repStep.title}` : "No step"} · {LNE[lang]} version{" "}
                <Button size="sm" onClick={() => setRep({ ...rep, t: player.current?.time() ?? rep.t })}>Use the current moment</Button></p>
              <div><span className="l">What is wrong?</span>
                <div className="chips" style={{ marginTop: 6 }}>{(cfg.data?.categories || []).map((c) => <Chip key={c} on={c === rep.cat} onClick={() => setRep({ ...rep, cat: c })}>{c}</Chip>)}</div></div>
              <div><Label htmlFor="repmsg">Tell the trainer what felt wrong</Label>
                <Textarea ref={msgRef} id="repmsg" value={rep.msg} required placeholder="For example: the Kannada voice says one thing, but the video shows another"
                  onChange={(e) => setRep({ ...rep, msg: e.target.value })} /></div>
              <div className="row"><Button variant="primary" disabled={sending} onClick={send}>{sending ? "Sending…" : "Send report"}</Button>
                <span className="tiny muted">The trainer sees this moment with your message. Their reply shows in My progress.</span></div>
            </Card>
          )}
          <Card><b className="small">Language</b><div style={{ marginTop: 8 }}><LangBar langs={video.langs} cur={lang} onPick={setLang} /></div></Card>
        </div>
        <div className="stack" style={{ gap: 8 }}>
          <h3>Steps</h3>
          <StepList steps={steps} lang={lang} active={active} onPick={(s) => player.current?.seek(s.start_s + 0.05, true)} />
        </div>
      </div>
    </>
  );
}
