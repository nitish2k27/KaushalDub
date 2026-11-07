export const LN: Record<string, string> = { en: "English", hi: "हिन्दी", kn: "ಕನ್ನಡ" };
export const LNE: Record<string, string> = { en: "English", hi: "Hindi", kn: "Kannada" };

export const fmt = (s: number | null | undefined) => {
  const t = Math.max(0, Math.floor(s || 0));
  return Math.floor(t / 60) + ":" + String(t % 60).padStart(2, "0");
};

export function ago(iso?: string | null) {
  if (!iso) return "";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return "Just now";
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  if (d < 172800) return "Yesterday";
  if (d < 7 * 86400) return `${Math.floor(d / 86400)} days ago`;
  return new Date(iso).toLocaleDateString();
}

export const hue = (label: string) => {
  if (label === "background") return 215;
  let h = 0;
  for (const c of label) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
};

export const labelName = (l: string) => (l === "background" ? "No action" : l);

export const STATUS: Record<string, { text: string; tone: "good" | "warn" | "bad" | "gray" | "" }> = {
  queued: { text: "Queued", tone: "gray" },
  processing: { text: "Processing", tone: "" },
  review: { text: "In review", tone: "warn" },
  dubbing: { text: "Dubbing", tone: "" },
  ready: { text: "Ready", tone: "good" },
  failed: { text: "Failed", tone: "bad" },
  needs_credits: { text: "Needs credits", tone: "bad" },
  open: { text: "Open", tone: "warn" },
  resolved: { text: "Resolved", tone: "good" },
  closed: { text: "Closed", tone: "gray" },
  pending: { text: "Pending", tone: "warn" },
  approved: { text: "Approved", tone: "good" },
  partly_approved: { text: "Partly approved", tone: "good" },
  sent_back: { text: "Sent back", tone: "gray" },
  draft: { text: "Draft", tone: "gray" },
  submitted: { text: "Waiting for review", tone: "warn" },
  accepted: { text: "Accepted", tone: "good" },
  partly_accepted: { text: "Partly accepted", tone: "good" },
};

export const PROVIDER_NAMES: Record<string, string> = {
  whisper: "Whisper (local)",
  indicconformer: "IndicConformer (local)",
  sarvam: "Sarvam",
  indictrans2: "IndicTrans2 (local)",
  indicparler: "Indic Parler-TTS (local)",
};
