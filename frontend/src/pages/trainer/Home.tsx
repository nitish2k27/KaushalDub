import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { useConfig, usePlan, videoRoute } from "@/lib/hooks";
import { ago, LN, LNE } from "@/lib/format";
import type { Video } from "@/lib/types";
import { Icon } from "@/components/Icon";
import { useTrainerCounts } from "@/components/Shell";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card, Chip, ErrorBox, Input, Label, Loading, Pill, Progress, Select, StatusPill } from "@/components/ui/primitives";

export default function TrainerHome() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const cfg = useConfig();
  const plan = usePlan();
  const { open, pending } = useTrainerCounts(true);
  const videos = useQuery({ queryKey: ["myvideos"], queryFn: () => api<(Video & { job: { status: string; progress: number } | null })[]>("/videos"),
    refetchInterval: (q) => (q.state.data?.some((v) => ["queued", "processing", "dubbing"].includes(v.status)) ? 4000 : false) });

  const [file, setFile] = useState<File | null>(null);
  const [yt, setYt] = useState("");
  const [title, setTitle] = useState("");
  const [task, setTask] = useState("PerformCPR");
  const [spoken, setSpoken] = useState("auto");
  const [langs, setLangs] = useState<string[]>(["kn", "hi"]);
  const [voice, setVoice] = useState("Female");
  const [dubMode, setDubMode] = useState<"steps" | "full">("steps");
  const [quiz, setQuiz] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const p = plan.data;
  const hasSource = !!file || /^https?:\/\/(www\.|m\.)?(youtube\.com|youtu\.be)\//.test(yt.trim());
  const canProcess = !!p?.can_process && hasSource && langs.length > 0 && title.trim().length > 0 && !busy;

  const pickFile = (f: File | undefined | null) => {
    if (!f) return;
    if (!f.type.startsWith("video/")) { toast("Choose a video file (MP4, MOV or WebM)"); return; }
    setFile(f);
    setYt("");
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "));
  };

  const process = async () => {
    setBusy(true);
    setErr(null);
    const form = new FormData();
    form.set("title", title.trim());
    form.set("task", task);
    form.set("targets", langs.join(","));
    form.set("spoken_lang", spoken);
    form.set("voice", voice);
    form.set("dub_mode", dubMode);
    form.set("quiz", String(quiz));
    if (file) form.set("file", file);
    else form.set("youtube_url", yt.trim());
    try {
      const r = await api<{ video_id: string; job_id: string }>("/videos", { form });
      qc.invalidateQueries({ queryKey: ["plan"] });
      qc.invalidateQueries({ queryKey: ["myvideos"] });
      nav(`/t/videos/${r.video_id}/processing`);
    } catch (e) {
      setErr(e);
      if (e instanceof ApiError && e.status === 402) qc.invalidateQueries({ queryKey: ["plan"] });
    } finally {
      setBusy(false);
    }
  };

  const quota = !p ? null : p.plan === "free" ? (
    p.free_left ? <p className="tiny muted">Uses 1 of your {p.free_left} remaining free videos. <Link className="btn sm" to="/t/settings">Plan</Link></p>
      : <><p className="small" style={{ color: "var(--bad)" }}>{p.blocked_reason}</p><Link className="btn sm" to="/t/settings">Add API keys</Link></>
  ) : p.plan === "byok" ? (
    p.can_process ? <p className="tiny muted">Runs on your own API keys.</p>
      : <><p className="small" style={{ color: "var(--bad)" }}>{p.blocked_reason}</p><Link className="btn sm" to="/t/settings">Add API keys</Link></>
  ) : <p className="tiny muted">Runs on the free local models on the GPU worker. Slower.</p>;

  const domains = cfg.data?.domains || [];
  return (
    <div className="stack">
      {(open > 0 || pending > 0) && (
        <div className="banner">
          <Icon name="flag" />
          <span className="grow small">
            {open > 0 && <><b>{open} learner report{open > 1 ? "s" : ""}</b> waiting</>}
            {open > 0 && pending > 0 && " · "}
            {pending > 0 && <><b>{pending} annotation request{pending > 1 ? "s" : ""}</b> to approve</>}
          </span>
          {open > 0 && <Link className="btn sm" to="/t/reports">Open reports</Link>}
          {pending > 0 && <Link className="btn sm" to="/t/annotations">Review corrections</Link>}
        </div>
      )}
      <div><h2>Upload a video</h2><p className="muted small">Short demonstrations of one task work best (under 10 minutes).</p></div>
      <div className="grid2">
        <Card className="stack">
          <div className={`drop ${file || drag ? "has" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); pickFile(e.dataTransfer.files[0]); }}>
            {file ? (
              <div className="stack" style={{ alignItems: "center", gap: 8 }}>
                <Pill tone="good"><Icon name="check" />Ready</Pill>
                <b style={{ wordBreak: "break-all" }}>{file.name}</b>
                <span className="muted small">{(file.size / 1e6).toFixed(1)} MB</span>
                <Button size="sm" onClick={() => setFile(null)}>Remove</Button>
              </div>
            ) : (
              <div className="stack" style={{ alignItems: "center", gap: 10 }}>
                <span style={{ color: "var(--brand)" }}><Icon name="upload" /></span>
                <b>Drop a video here</b><span className="muted small">MP4, MOV or WebM, up to 300 MB</span>
                <Button size="sm" variant="primary" onClick={() => fileRef.current?.click()}>Choose file</Button>
                <input ref={fileRef} id="file" type="file" accept="video/*" hidden onChange={(e) => pickFile(e.target.files?.[0])} />
              </div>
            )}
          </div>
          {!file && (
            <div><Label htmlFor="yt">…or paste a YouTube link</Label>
              <Input id="yt" type="text" inputMode="url" placeholder="https://www.youtube.com/watch?v=…" value={yt} onChange={(e) => setYt(e.target.value)} /></div>
          )}
          <div><Label htmlFor="title">Video title</Label><Input id="title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="For example: CPR on an adult" /></div>
        </Card>
        <Card className="stack">
          <div><Label htmlFor="task">Skill</Label>
            <select id="task" value={task} onChange={(e) => setTask(e.target.value)}>
              {domains.map((d) => (
                <optgroup key={d} label={d}>
                  {cfg.data!.tasks.filter((t) => t.domain === d).map((t) => <option key={t.id} value={t.id}>{t.title}{t.fewshot ? " (few-shot)" : ""}</option>)}
                </optgroup>
              ))}
            </select>
          </div>
          <div><Label htmlFor="spoken">Spoken language</Label>
            <Select id="spoken" value={spoken} onChange={(e) => setSpoken(e.target.value)}
              options={[{ value: "auto", label: "Detect automatically" }, { value: "en", label: "English" }, { value: "hi", label: "Hindi" }, { value: "kn", label: "Kannada" }]} /></div>
          <div><span className="l">Dub into</span>
            <div className="chips" style={{ marginTop: 6 }}>
              {["kn", "hi"].map((l) => (
                <Chip key={l} on={langs.includes(l)} onClick={() => setLangs(langs.includes(l) ? langs.filter((x) => x !== l) : [...langs, l])}>
                  {LNE[l]} · {LN[l]}
                </Chip>
              ))}
              <button className="chip" disabled style={{ opacity: 0.5 }}>Tamil · soon</button>
            </div>
          </div>
          <fieldset className="stack" style={{ gap: 6, border: 0, padding: 0, margin: 0 }}>
            <legend className="l">Narration style</legend>
            <label className="row" style={{ gap: 8, alignItems: "flex-start" }}>
              <input type="radio" name="dubmode" checked={dubMode === "steps"} onChange={() => setDubMode("steps")} style={{ width: 20, height: 20, marginTop: 2 }} />
              <span><b className="small">Step narration</b><br /><span className="tiny muted">A short narrator line for each detected step. About ₹4 per video.</span></span>
            </label>
            <label className="row" style={{ gap: 8, alignItems: "flex-start" }}>
              <input type="radio" name="dubmode" checked={dubMode === "full"} onChange={() => setDubMode("full")} style={{ width: 20, height: 20, marginTop: 2 }} />
              <span><b className="small">Full speech translation</b><br /><span className="tiny muted">Everything the instructor says, translated and voiced at the moment it is said; original voice turned down. About ₹10–20 per video.</span></span>
            </label>
          </fieldset>
          <div><Label htmlFor="voice">Narrator voice</Label><Select id="voice" value={voice} onChange={(e) => setVoice(e.target.value)} options={["Female", "Male"]} /></div>
          <label className="row" style={{ gap: 8 }}><input type="checkbox" checked={quiz} onChange={(e) => setQuiz(e.target.checked)} style={{ width: 20, height: 20 }} /> Generate a quiz for learners</label>
          <Button variant="primary" disabled={!canProcess} onClick={process}>{busy ? "Uploading…" : "Process video"}</Button>
          {!hasSource && <p className="tiny muted">Choose a file or paste a YouTube link to enable processing.</p>}
          <ErrorBox error={err} />
          {quota}
        </Card>
      </div>
      <Card>
        <h3 style={{ marginBottom: 10 }}>History</h3>
        {videos.isLoading ? <Loading /> : <ErrorBox error={videos.error} />}
        <div className="tw">
          <table>
            <thead><tr><th>Video</th><th>Skill</th><th>Languages</th><th>Status</th><th>When</th><th></th></tr></thead>
            <tbody>
              {videos.data?.length === 0 && <tr><td colSpan={6} className="muted">No videos yet. Upload your first one above.</td></tr>}
              {videos.data?.map((v) => (
                <tr key={v.id}>
                  <td><b>{v.title}</b>{v.job && ["queued", "running"].includes(v.job.status) && <Progress value={v.job.progress} className="mt-1" label="Job progress" />}</td>
                  <td>{v.task_title}<br /><span className="tiny muted">{v.domain}</span></td>
                  <td>{v.langs.map((l) => l.toUpperCase()).join(" · ")}</td>
                  <td>{v.published ? <Pill tone="good">Published</Pill> : <StatusPill status={v.status} />}</td>
                  <td className="muted">{ago(v.created_at)}</td>
                  <td><Link className="btn sm" to={videoRoute(v)}>Open</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
