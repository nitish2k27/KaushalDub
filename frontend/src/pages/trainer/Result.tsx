import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useVideo } from "@/lib/hooks";
import { LNE } from "@/lib/format";
import type { Job, Step, Video } from "@/lib/types";
import { Icon } from "@/components/Icon";
import { LangBar, Pipe } from "@/components/bits";
import { captionFromSteps, Player, type PlayerHandle } from "@/components/Player";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card, ErrorBox, Loading, Pill, Textarea } from "@/components/ui/primitives";

export async function waitForJob(jobId: string, onTick?: (j: Job) => void): Promise<Job> {
  for (;;) {
    const j = await api<Job>(`/jobs/${jobId}`);
    onTick?.(j);
    if (!["queued", "running"].includes(j.status)) return j;
    await new Promise((r) => setTimeout(r, 1500));
  }
}

export function sourcesFor(video: Video, lang: string, narration: boolean) {
  const o = video.outputs?.[lang];
  const vtt = o?.vtt || null;
  if (!narration || !o?.dubbed) return { src: video.source_url || o?.mp4 || null, vtt };
  return { src: o.mp4, vtt };
}

export default function Result() {
  const { id } = useParams();
  const v = useVideo(id);
  if (v.isLoading) return <Loading />;
  if (v.error || !v.data) return <ErrorBox error={v.error || "Video not found"} />;
  return <ResultBody video={v.data} />;
}

function ResultBody({ video }: { video: Video }) {
  const qc = useQueryClient();
  const toast = useToast();
  const player = useRef<PlayerHandle>(null);
  const [lang, setLang] = useState(video.targets[0] || "en");
  const [narr, setNarr] = useState(true);
  const [active, setActive] = useState<number | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const steps = video.steps || [];
  const { src, vtt } = sourcesFor(video, lang, narr);
  const refresh = (fresh?: Video) => (fresh ? qc.setQueryData(["video", video.id], fresh) : qc.invalidateQueries({ queryKey: ["video", video.id] }));

  const publish = async (on: boolean) => {
    setBusy("publish");
    try {
      refresh(await api<Video>(`/videos/${video.id}/${on ? "publish" : "unpublish"}`, { method: "POST" }));
      qc.invalidateQueries({ queryKey: ["myvideos"] });
      toast(on ? "Published to the learner library" : "Removed from the library");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed");
    }
    setBusy(null);
  };

  const saveText = async (s: Step, revoice: boolean) => {
    setBusy(`s${s.idx}`);
    try {
      refresh(await api<Video>(`/videos/${video.id}/steps/${s.idx}/text`, { method: "PUT", query: { lang }, body: { text } }));
      if (revoice && lang !== "en") {
        const r = await api<{ job_id: string }>(`/videos/${video.id}/steps/${s.idx}/revoice`, { method: "POST", query: { lang } });
        toast(`Re-making the ${LNE[lang]} voice for step ${s.idx}…`);
        const j = await waitForJob(r.job_id);
        toast(j.status === "done" ? `Voice re-made for step ${s.idx}` : j.error || "Re-voicing failed");
        refresh();
      } else toast("Text saved. Captions updated.");
      setEditing(null);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed");
    }
    setBusy(null);
  };

  const o = video.outputs?.[lang];
  return (
    <>
      <Pipe n={video.published ? 5 : 4} />
      <div className="row" style={{ marginBottom: 14 }}>
        <div className="grow">
          <h2>{video.title}</h2>
          <p className="muted small">Dubbed in {video.targets.map((l) => LNE[l]).join(" and ")} · {steps.length} steps · {video.quiz?.items.length ? "quiz included" : "no quiz"} · {video.dub_mode === "full" ? "full speech translation" : "step narration"}</p>
        </div>
        {o?.dubbed && o.mp4 && <a className="btn" href={o.mp4} download={`${video.title}_${lang}.mp4`}><Icon name="dl" />Download .mp4</a>}
        {o?.vtt && <a className="btn" href={o.vtt} download={`${video.title}_${lang}.vtt`}><Icon name="dl" />Captions .vtt</a>}
        {video.published ? (
          <><Pill tone="good"><Icon name="check" />Published</Pill><Button size="sm" disabled={!!busy} onClick={() => publish(false)}>Unpublish</Button></>
        ) : <Button variant="primary" disabled={!!busy || video.status !== "ready"} onClick={() => publish(true)}>Publish to learner library</Button>}
      </div>
      {video.status !== "ready" && <div className="banner" style={{ marginBottom: 12 }}><Icon name="flag" /><span className="small grow">Status: {video.status}. {video.last_error || ""}</span></div>}
      <div className="grid2">
        <div className="stack">
          <Player ref={player} src={src} vtt={vtt} lang={lang} steps={steps} captionText={captionFromSteps(steps, lang)} onStep={setActive}
            badge={narr && o?.dubbed ? "Dubbed preview" : "Original audio"} durationHint={video.duration_s}
            narration={video.outputs?.[lang]?.dubbed ? { on: narr, toggle: () => setNarr(!narr) } : null} />
          <Card>
            <b className="small">Listen in</b>
            <div style={{ marginTop: 8 }}><LangBar langs={video.langs} cur={lang} onPick={setLang} /></div>
            <p className="tiny muted" style={{ marginTop: 8 }}>{lang === "en" ? "English plays the original audio with English captions." : "Press play to hear the narration for the chosen language."}</p>
          </Card>
        </div>
        <div className="stack" style={{ gap: 8 }}>
          <h3>Detected steps</h3>
          {steps.map((s) => (
            <div key={s.id} className={`step ${s.idx === active ? "on" : ""}`} style={{ cursor: "default", flexDirection: "column" }}>
              <div className="row" style={{ gap: 12, width: "100%" }}>
                <button className="n" style={{ cursor: "pointer" }} aria-label={`Play step ${s.idx}`} onClick={() => player.current?.seek(s.start_s + 0.05, true)}>{s.idx}</button>
                <span className="grow"><b>{s.title}</b><br /><span className="small muted" lang={lang}>{s.texts[lang] || s.narration_en}</span></span>
                {editing !== s.idx && <Button size="sm" onClick={() => { setEditing(s.idx); setText(s.texts[lang] || s.narration_en); }}>Edit</Button>}
              </div>
              {editing === s.idx && (
                <div className="stack" style={{ gap: 8, width: "100%" }}>
                  <label className="l" htmlFor={`t${s.idx}`}>{LNE[lang]} narration and caption</label>
                  <Textarea id={`t${s.idx}`} lang={lang} value={text} onChange={(e) => setText(e.target.value)} />
                  <div className="row">
                    <Button size="sm" variant="primary" disabled={!!busy} onClick={() => saveText(s, lang !== "en")}>
                      {busy === `s${s.idx}` ? "Working…" : lang !== "en" ? "Save and re-make voice" : "Save"}</Button>
                    {lang !== "en" && <Button size="sm" disabled={!!busy} onClick={() => saveText(s, false)}>Save text only</Button>}
                    <Button size="sm" onClick={() => setEditing(null)}>Cancel</Button>
                  </div>
                </div>
              )}
            </div>
          ))}
          <div className="row">
            <Link className="btn" to={`/t/videos/${video.id}/review`}>Edit English steps</Link>
            <Link className="btn" to="/t">Back to my videos</Link>
          </div>
        </div>
      </div>
    </>
  );
}
