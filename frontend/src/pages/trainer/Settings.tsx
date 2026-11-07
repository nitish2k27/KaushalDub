import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { usePlan } from "@/lib/hooks";
import { PROVIDER_NAMES } from "@/lib/format";
import type { Plan } from "@/lib/types";
import { Icon } from "@/components/Icon";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card, ErrorBox, Label, Loading, Pill, Progress, Select } from "@/components/ui/primitives";

const KEYS: [string, string, string][] = [["sarvam", "Sarvam", "speech, translation, voice (required)"],
  ["gemini", "Gemini", "step text and quiz"], ["groq", "Groq", "backup for step text"]];

export default function Settings() {
  const plan = usePlan();
  if (plan.isLoading) return <Loading />;
  if (plan.error || !plan.data) return <ErrorBox error={plan.error} />;
  return <SettingsBody p={plan.data} />;
}

function SettingsBody({ p }: { p: Plan }) {
  const qc = useQueryClient();
  const toast = useToast();
  const nav = useNavigate();
  const [mode, setMode] = useState(p.plan);
  const [asr, setAsr] = useState(p.asr);
  const [mt, setMt] = useState(p.mt);
  const [tts, setTts] = useState(p.tts);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Record<string, { ok: boolean; text: string }>>({});
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { setMode(p.plan); }, [p.plan]);
  const set = (fresh: Plan) => qc.setQueryData(["plan"], fresh);

  const saveKey = async (k: string) => {
    const val = (keys[k] || "").trim();
    if (!val) return true;
    if (val.length < 12) { setMsgs((m) => ({ ...m, [k]: { ok: false, text: "That key looks too short. Paste the full key." } })); return false; }
    set(await api<Plan>(`/me/keys/${k}`, { method: "PUT", body: { key: val } }));
    setKeys((x) => ({ ...x, [k]: "" }));
    return true;
  };

  const test = async (k: string) => {
    setBusy(k);
    try {
      if (await saveKey(k)) {
        const r = await api<{ ok: boolean; message: string; plan: Plan }>(`/me/keys/${k}/test`, { method: "POST" });
        set(r.plan);
        setMsgs((m) => ({ ...m, [k]: { ok: r.ok, text: r.message } }));
      }
    } catch (e) {
      setMsgs((m) => ({ ...m, [k]: { ok: false, text: e instanceof Error ? e.message : "Failed" } }));
    }
    setBusy(null);
  };

  const remove = async (k: string) => {
    setBusy(k);
    try { set(await api<Plan>(`/me/keys/${k}`, { method: "DELETE" })); setMsgs((m) => ({ ...m, [k]: { ok: true, text: "Key removed" } })); }
    catch (e) { toast(e instanceof Error ? e.message : "Failed"); }
    setBusy(null);
  };

  const save = async () => {
    setBusy("save");
    setErr(null);
    try {
      for (const [k] of KEYS) if (!(await saveKey(k))) throw new Error("Fix the key first");
      set(await api<Plan>("/me/plan", { method: "PUT", body: { plan: mode, asr, mt, tts } }));
      toast("Settings saved");
      nav("/t");
    } catch (e) {
      setErr(e);
    }
    setBusy(null);
  };

  const card = (id: Plan["plan"], title: string, sub: string) => (
    <label className={`plan ${mode === id ? "on" : ""}`}>
      <span className="row" style={{ gap: 8 }}><input type="radio" name="plan" value={id} checked={mode === id} onChange={() => setMode(id)} /><b>{title}</b>
        {p.plan === id && <Pill tone="good">Current</Pill>}</span>
      <span className="small muted">{sub}</span>
    </label>
  );
  const local = mode === "local";
  return (
    <div className="stack">
      <div><h2>API keys and plan</h2><p className="muted small">Dubbing uses paid speech, translation and voice services. Choose who pays for them.</p></div>
      <Card className="stack" style={{ gap: 10 }}>
        <div className="row"><h3>Free trial</h3><span className="grow" /><Pill tone={p.free_left ? "good" : "bad"}>{p.free_left} of {p.free_total} free videos left</Pill></div>
        <Progress value={(p.free_used / p.free_total) * 100} label="Free videos used" />
        <p className="small muted">Your first {p.free_total} videos run on KaushalDub’s keys. After that, use your own keys, the free local models, or upgrade.</p>
      </Card>
      <div className="plans">
        {card("free", "Free trial", `${p.free_total} videos on our keys`)}
        {card("byok", "Your own API keys", "No limit. You pay Sarvam, Gemini or Groq directly.")}
        {card("local", "Free local models", "AI4Bharat open-source models on a GPU worker. No keys, slower.")}
        <div className="plan off"><b>Pro</b><span className="small muted">Our keys, no limit</span><Button size="sm" disabled>Coming soon</Button>
          <span className="tiny muted">Payments are not set up yet.</span></div>
      </div>
      {local && !p.gpu_queue_enabled && (
        <div className="banner"><Icon name="flag" /><span className="small grow">The GPU worker is not switched on for this server, so local jobs run on the CPU worker. Whisper and IndicTrans2 work there; Indic Parler-TTS and IndicConformer need the GPU notebook.</span></div>
      )}
      {(mode === "byok" || Object.keys(p.keys).length > 0) && (
        <Card className="stack" style={{ gap: 12 }}>
          <h3>Your keys</h3>
          {KEYS.map(([k, name, use]) => {
            const saved = p.keys[k];
            return (
              <div key={k}>
                <div className="keyrow">
                  <div>
                    <Label htmlFor={`key_${k}`}>{name} API key <span className="muted" style={{ fontWeight: 400 }}>· {use}</span></Label>
                    <input type="password" id={`key_${k}`} autoComplete="off" spellCheck={false} value={keys[k] || ""}
                      placeholder={saved ? `Saved ••••${saved.last4}${saved.verified_at ? " · works" : ""} (paste to replace)` : `Paste your ${name} key`}
                      onChange={(e) => setKeys((x) => ({ ...x, [k]: e.target.value }))} />
                  </div>
                  <div className="row" style={{ gap: 6 }}>
                    <Button size="sm" disabled={busy === k || (!saved && !keys[k])} onClick={() => test(k)}>
                      {saved?.verified_at && !keys[k] ? <><Icon name="check" />Works</> : busy === k ? "Testing…" : "Test"}</Button>
                    {saved && <Button size="sm" aria-label={`Remove ${name} key`} disabled={busy === k} onClick={() => remove(k)}>✕</Button>}
                  </div>
                </div>
                {msgs[k] && <p className="tiny" style={{ marginTop: 4, color: msgs[k].ok ? "var(--good)" : "var(--bad)" }}>{msgs[k].text}</p>}
              </div>
            );
          })}
          <p className="tiny muted">Keys are encrypted on the server, used only for your videos, and never shown again in full. The Test button makes one tiny request to the provider.</p>
        </Card>
      )}
      <Card className="stack" style={{ gap: 12 }}>
        <h3>Which models to use</h3>
        <div className="plans">
          <div><Label htmlFor="pasr">Speech to text</Label><Select id="pasr" value={asr} onChange={(e) => setAsr(e.target.value)}
            options={["whisper", "indicconformer", "sarvam"].map((v) => ({ value: v, label: PROVIDER_NAMES[v], disabled: local && v === "sarvam" }))} /></div>
          <div><Label htmlFor="pmt">Translation</Label><Select id="pmt" value={mt} onChange={(e) => setMt(e.target.value)}
            options={["indictrans2", "sarvam"].map((v) => ({ value: v, label: v === "sarvam" ? "Sarvam Translate" : PROVIDER_NAMES[v], disabled: local && v === "sarvam" }))} /></div>
          <div><Label htmlFor="ptts">Voice</Label><Select id="ptts" value={tts} onChange={(e) => setTts(e.target.value)}
            options={["indicparler", "sarvam"].map((v) => ({ value: v, label: v === "sarvam" ? "Sarvam Bulbul" : PROVIDER_NAMES[v], disabled: local && v === "sarvam" }))} /></div>
        </div>
        <p className="tiny muted">If a provider runs out of credits, the job falls back to the next one (Sarvam → local model, Gemini → Groq → template). If none is left, the job pauses and asks you to add credits.</p>
      </Card>
      <ErrorBox error={err} />
      <div className="row"><Button variant="primary" disabled={!!busy} onClick={save}>Save settings</Button></div>
    </div>
  );
}
