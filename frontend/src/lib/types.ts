export type Role = "trainer" | "learner" | "annotator";

export interface User {
  id: string; email: string; name: string; role: Role; avatar_url?: string | null; is_admin?: boolean;
  budget?: { spent_inr: number; budget_inr: number; remaining_inr: number; exhausted: boolean; low: boolean };
}

export interface Stage { key: string; label: string; status: "wait" | "run" | "done" | "failed"; provider?: string | null }
export interface Job {
  id: string; video_id: string | null; kind: string; status: string; stage: string; progress: number;
  error: string | null; stages: Stage[]; logs: { t: string; level: string; msg: string }[];
  cost?: { inr: number; audio_min: number; mt_chars: number; tts_chars: number }; queue?: string; key_source?: string;
  created_at?: string; finished_at?: string | null;
}

export interface Step {
  id: string; idx: number; start_s: number; end_s: number; label: string; confidence: number; low_conf: boolean;
  title: string; instruction: string; narration_en: string; edited?: boolean; needs_review?: boolean;
  keyframe_url?: string | null; texts: Record<string, string>;
}

export interface QuizItem { q: string; options: string[]; answer: number }
export interface Output { mp4: string | null; vtt: string | null; narration: string | null; dubbed: boolean }

export interface Video {
  id: string; title: string; task: string; task_title: string; domain: string; spoken_lang: string; targets: string[];
  langs: string[]; status: string; duration_s: number | null; created_at: string; published: boolean; by: string;
  is_owner: boolean; thumb_url?: string | null; voice?: string; quiz_enabled?: boolean; dub_mode?: "steps" | "full"; llm?: string | null;
  llm_fallback?: boolean; order_ok?: boolean; model_kind?: string; last_error?: string | null; steps?: Step[];
  quiz?: { id: string; items: QuizItem[]; translations: Record<string, QuizItem[]> } | null;
  outputs?: Record<string, Output>; source_url?: string | null;
  transcript?: { start: number; end: number; text: string }[]; job?: Job | null;
}

export interface Plan {
  plan: "free" | "byok" | "local" | "pro"; free_used: number; free_total: number; free_left: number;
  asr: string; mt: string; tts: string; keys: Record<string, { last4: string; verified_at: string | null; saved: boolean }>;
  can_process: boolean; blocked_reason: string | null; gpu_queue_enabled: boolean;
}

export interface Ticket {
  id: string; video_id: string; video_title: string; reporter_name?: string; lang: string; timestamp_s: number;
  step_idx: number | null; category: string; message: string; status: "open" | "resolved" | "closed";
  reply: string | null; created_at: string; closed_at: string | null;
}

export interface Segment { label: string; start: number; end: number; confidence?: number | null; accepted?: boolean; unclear?: boolean }
export interface Change {
  id: number; start: number; end: number; label: string; from: string; confidence: number | null;
  kind: "label" | "boundary" | "both";
}
export interface AnnRequest {
  id: string; video_id: string; video_title: string; annotator_name: string; status: string; note: string | null;
  created_at: string; changes: Change[]; model_segments?: Segment[]; annotator_segments?: Segment[];
}

export interface AppConfig {
  tasks: { id: string; title: string; domain: string; fewshot?: boolean }[]; domains: string[];
  langs: Record<string, string>; target_langs: string[]; categories: string[];
  providers: { asr: string[]; mt: string[]; tts: string[] };
}
