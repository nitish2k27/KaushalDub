-- Full-speech dubbing: per video choose step narration (default) or a translation of everything the instructor says.
alter table public.videos add column if not exists dub_mode text not null default 'steps'
  check (dub_mode in ('steps', 'full'));
-- Translated sentences of the transcript, cached per language: {"src_hash": "...", "en": [...], "hi": [...], "kn": [...]}
alter table public.videos add column if not exists segment_texts jsonb;
