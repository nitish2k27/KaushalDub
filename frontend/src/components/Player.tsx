import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { fmt } from "@/lib/format";
import type { Step } from "@/lib/types";
import { Icon } from "./Icon";

export interface PlayerHandle {
  seek: (t: number, play?: boolean) => void;
  pause: () => void;
  play: () => void;
  time: () => number;
  playRange: (a: number, b: number) => void;
}

interface Props {
  src?: string | null;             // per-language mp4 (dubbed) or the original
  vtt?: string | null;             // captions for the chosen language (<track>, rendered in the overlay)
  lang: string;
  steps?: Step[];
  captionText?: (t: number) => string;  // fallback captions (e.g. before the dub exists)
  badge?: string;
  startAt?: number;
  narration?: { on: boolean; toggle: () => void } | null;
  onStep?: (idx: number | null) => void;
  onTime?: (t: number, duration: number) => void;
  label?: string;
  durationHint?: number | null;
}

export const stepIdxAt = (steps: Step[] | undefined, t: number) => {
  let cur: number | null = steps?.length ? steps[0].idx : null;
  for (const s of steps || []) if (s.start_s <= t) cur = s.idx;
  return cur;
};

/** Native <video> with the mockup's controls. Switching language swaps the source but keeps the time. */
export const Player = forwardRef<PlayerHandle, Props>(function Player(
  { src, vtt, lang, steps, captionText, badge, startAt, narration, onStep, onTime, label, durationHint }, ref) {
  const v = useRef<HTMLVideoElement>(null);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(durationHint || 0);
  const [playing, setPlaying] = useState(false);
  const [cue, setCue] = useState<string | null>(null);
  const [hasCues, setHasCues] = useState(false);
  const resume = useRef<{ t: number; play: boolean } | null>(null);
  const stopAt = useRef<number | null>(null);
  const lastStep = useRef<number | null>(-1);

  useImperativeHandle(ref, () => ({
    seek: (time, play) => {
      const el = v.current;
      if (!el) return;
      el.currentTime = Math.max(0, time);
      if (play) void el.play().catch(() => {});
    },
    pause: () => v.current?.pause(),
    play: () => void v.current?.play().catch(() => {}),
    time: () => v.current?.currentTime ?? 0,
    playRange: (a, b) => {
      const el = v.current;
      if (!el) return;
      stopAt.current = b;
      el.currentTime = a + 0.05;
      void el.play().catch(() => {});
    },
  }));

  // keep the position when the source changes (language switch / narration toggle)
  const prevSrc = useRef(src);
  useEffect(() => {
    const el = v.current;
    if (el && prevSrc.current && prevSrc.current !== src) resume.current = { t: el.currentTime, play: !el.paused };
    prevSrc.current = src;
  }, [src]);

  useEffect(() => {
    setHasCues(false);
    setCue(null);
    const el = v.current;
    if (!el) return;
    const bind = () => {
      const tr = el.textTracks[0];
      if (!tr) return;
      tr.mode = "hidden";
      const upd = () => {
        const c = tr.activeCues && tr.activeCues.length ? (tr.activeCues[0] as VTTCue).text : null;
        setCue(c);
        setHasCues(!!tr.cues?.length);
      };
      tr.oncuechange = upd;
      upd();
    };
    const id = window.setTimeout(bind, 50);
    return () => window.clearTimeout(id);
  }, [vtt, src]);

  const onMeta = () => {
    const el = v.current!;
    setDur(el.duration || durationHint || 0);
    if (resume.current) {
      el.currentTime = resume.current.t;
      if (resume.current.play) void el.play().catch(() => {});
      resume.current = null;
    } else if (startAt) {
      el.currentTime = startAt;
    }
    const tr = el.textTracks[0];
    if (tr) tr.mode = "hidden";
  };

  const onTimeUpdate = () => {
    const el = v.current!;
    const now = el.currentTime;
    setT(now);
    if (stopAt.current !== null && now >= stopAt.current) {
      el.pause();
      stopAt.current = null;
    }
    const k = stepIdxAt(steps, now);
    if (k !== lastStep.current) {
      lastStep.current = k;
      onStep?.(k);
    }
    onTime?.(now, el.duration || dur);
  };

  useEffect(() => {
    lastStep.current = -1;
  }, [steps, lang]);

  const d = dur || durationHint || 0;
  const caption = (hasCues ? cue : null) ?? captionText?.(t) ?? "";
  return (
    <div className="vp">
      <video ref={v} src={src || undefined} crossOrigin="anonymous" playsInline preload="metadata" aria-label={label || "Skill video"}
        onLoadedMetadata={onMeta} onTimeUpdate={onTimeUpdate} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
        onClick={() => (v.current?.paused ? v.current.play().catch(() => {}) : v.current?.pause())}>
        {vtt && <track key={vtt} kind="captions" src={vtt} srcLang={lang} label={lang} default />}
      </video>
      {caption && <div className="cap" lang={lang} aria-live="off">{caption}</div>}
      {badge && <span className="watermark">{badge}</span>}
      {!src && <div className="cap" style={{ bottom: "45%" }}>Video not available</div>}
      <div className="vc">
        <button aria-label={playing ? "Pause" : "Play"} onClick={() => (v.current?.paused ? v.current.play().catch(() => {}) : v.current?.pause())}>
          <Icon name={playing ? "pause" : "play"} />
        </button>
        <div className="seekw">
          {d > 0 && steps?.slice(1).map((s) => <span key={s.id} className="tick" style={{ left: `${(s.start_s / d) * 100}%` }} />)}
          <input type="range" min={0} max={1000} value={d ? Math.round((t / d) * 1000) : 0} aria-label="Seek"
            onChange={(e) => { if (v.current && d) v.current.currentTime = (Number(e.target.value) / 1000) * d; }} />
        </div>
        <span className="tm">{fmt(t)} / {fmt(d)}</span>
        {narration && (
          <button className={`narr ${narration.on ? "on" : ""}`} onClick={narration.toggle} aria-pressed={narration.on}>
            <Icon name="vol" />&nbsp;Narration {narration.on ? "on" : "off"}
          </button>
        )}
        <button aria-label="Full screen" onClick={() => v.current?.parentElement?.requestFullscreen?.().catch(() => {})}>
          <Icon name="full" />
        </button>
      </div>
    </div>
  );
});

export function captionFromSteps(steps: Step[] | undefined, lang: string) {
  return (t: number) => {
    const s = (steps || []).find((x) => x.start_s <= t && t < x.end_s);
    return s ? s.texts[lang] || s.narration_en : "";
  };
}
