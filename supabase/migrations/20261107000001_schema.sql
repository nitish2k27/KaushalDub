-- KaushalDub schema. Apply with `supabase db push` or paste into the Supabase SQL editor (in file order).
create extension if not exists pgcrypto;

create table if not exists public.users (
  id uuid primary key references auth.users (id) on delete cascade,
  email text not null default '',
  name text not null default '',
  role text not null default 'learner' check (role in ('trainer', 'learner', 'annotator')),
  avatar_url text,
  created_at timestamptz not null default now()
);

create table if not exists public.videos (
  id uuid primary key default gen_random_uuid(),
  owner uuid not null references public.users (id) on delete cascade,
  title text not null,
  task text not null,
  domain text,
  spoken_lang text not null default 'auto',
  targets text[] not null default '{}',
  voice text not null default 'Female',
  quiz_enabled boolean not null default true,
  status text not null default 'queued'
    check (status in ('queued', 'processing', 'review', 'dubbing', 'ready', 'failed', 'needs_credits')),
  source_path text,
  thumb_path text,
  duration_s real,
  transcript jsonb,
  model_segments jsonb,           -- the step model's output (for annotator diffs)
  features jsonb,                 -- {path, fps, frames} of the stored CLIP features
  llm text,
  llm_fallback boolean,
  order_ok boolean,
  model_kind text,
  last_error text,
  published boolean not null default false,
  published_at timestamptz,
  approved_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists videos_owner_idx on public.videos (owner);
create index if not exists videos_published_idx on public.videos (published) where published;

create table if not exists public.steps (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null references public.videos (id) on delete cascade,
  idx int not null,
  start_s real not null,
  end_s real not null,
  label text not null,
  confidence real not null default 1,
  low_conf boolean not null default false,
  title text not null default '',
  instruction text not null default '',
  narration_en text not null default '',
  edited boolean not null default false,
  needs_review boolean not null default false,
  keyframe_path text,
  created_at timestamptz not null default now()
);
create index if not exists steps_video_idx on public.steps (video_id, idx);

create table if not exists public.translations (
  id uuid primary key default gen_random_uuid(),
  step_id uuid not null references public.steps (id) on delete cascade,
  video_id uuid not null references public.videos (id) on delete cascade,
  lang text not null,
  text text not null,
  provider text,
  source_hash text,
  edited boolean not null default false,
  created_at timestamptz not null default now(),
  unique (step_id, lang)
);

create table if not exists public.outputs (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null references public.videos (id) on delete cascade,
  lang text not null,
  mp4_path text,
  vtt_path text,
  narration_path text,
  placements jsonb,
  updated_at timestamptz default now(),
  created_at timestamptz not null default now(),
  unique (video_id, lang)
);

create table if not exists public.tts_clips (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null references public.videos (id) on delete cascade,
  lang text not null,
  idx int not null,
  hash text not null,
  path text not null,
  provider text,
  created_at timestamptz not null default now(),
  unique (video_id, lang, idx, hash)
);

create table if not exists public.quizzes (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null references public.videos (id) on delete cascade,
  items jsonb not null default '[]',
  translations jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists public.quiz_attempts (
  id uuid primary key default gen_random_uuid(),
  quiz_id uuid not null references public.quizzes (id) on delete cascade,
  video_id uuid not null references public.videos (id) on delete cascade,
  user_id uuid not null references public.users (id) on delete cascade,
  answers jsonb not null,
  lang text,
  score int not null,
  total int not null,
  created_at timestamptz not null default now()
);

create table if not exists public.watch_history (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  video_id uuid not null references public.videos (id) on delete cascade,
  progress real not null default 0,
  lang text,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (user_id, video_id)
);

create table if not exists public.tickets (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null references public.videos (id) on delete cascade,
  trainer_id uuid not null references public.users (id) on delete cascade,
  reporter_id uuid not null references public.users (id) on delete cascade,
  lang text not null,
  timestamp_s real not null,
  step_idx int,
  category text not null check (category in ('Wrong step', 'Wrong translation', 'Narration out of sync',
                                             'Unclear instruction', 'Unsafe instruction', 'Other')),
  message text not null check (length(trim(message)) > 0),
  status text not null default 'open' check (status in ('open', 'resolved', 'closed')),
  reply text,
  fixed_text boolean,
  created_at timestamptz not null default now(),
  closed_at timestamptz
);
create index if not exists tickets_trainer_idx on public.tickets (trainer_id, status);

create table if not exists public.annotations (
  id uuid primary key default gen_random_uuid(),
  clip_id uuid not null references public.videos (id) on delete cascade,
  annotator uuid not null references public.users (id) on delete cascade,
  segments jsonb not null default '[]',
  status text not null default 'draft'
    check (status in ('draft', 'submitted', 'accepted', 'partly_accepted', 'sent_back')),
  reviewer_note text,
  request_id uuid,
  updated_at timestamptz default now(),
  created_at timestamptz not null default now(),
  unique (clip_id, annotator)
);

create table if not exists public.annotation_requests (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null references public.videos (id) on delete cascade,
  annotator_id uuid not null references public.users (id) on delete cascade,
  trainer_id uuid not null references public.users (id) on delete cascade,
  model_segments jsonb not null,
  annotator_segments jsonb not null,
  changes jsonb not null default '[]',
  approved_changes jsonb not null default '[]',
  status text not null default 'pending' check (status in ('pending', 'approved', 'partly_approved', 'sent_back')),
  note text,
  reviewed_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists annreq_trainer_idx on public.annotation_requests (trainer_id, status);

create table if not exists public.correction_memory (
  id uuid primary key default gen_random_uuid(),
  task text not null,
  label text not null,
  feature_path text not null,
  source_request_id uuid references public.annotation_requests (id) on delete set null,
  video_id uuid references public.videos (id) on delete set null,
  start_s real,
  end_s real,
  used_in_version int,            -- null = waiting for retraining
  created_at timestamptz not null default now()
);
create index if not exists memory_task_idx on public.correction_memory (task);

create table if not exists public.model_versions (
  id uuid primary key default gen_random_uuid(),
  version int not null unique,
  path text not null,             -- 'bundle' = the shipped bundle, else a folder in the outputs bucket
  metrics jsonb,
  active boolean not null default false,
  created_at timestamptz not null default now()
);
create unique index if not exists one_active_model on public.model_versions (active) where active;

create table if not exists public.user_plans (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references public.users (id) on delete cascade,
  plan text not null default 'free' check (plan in ('free', 'byok', 'local', 'pro')),
  free_used int not null default 0 check (free_used >= 0),
  asr text not null default 'sarvam' check (asr in ('whisper', 'indicconformer', 'sarvam')),
  mt text not null default 'sarvam' check (mt in ('indictrans2', 'sarvam')),
  tts text not null default 'sarvam' check (tts in ('indicparler', 'sarvam')),
  updated_at timestamptz default now(),
  created_at timestamptz not null default now()
);

create table if not exists public.user_api_keys (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  provider text not null check (provider in ('sarvam', 'gemini', 'groq')),
  encrypted_key text not null,    -- Fernet ciphertext; the plain key never reaches the database
  last4 text,
  verified_at timestamptz,
  updated_at timestamptz default now(),
  created_at timestamptz not null default now(),
  unique (user_id, provider)
);

create table if not exists public.jobs (
  id uuid primary key default gen_random_uuid(),
  video_id uuid references public.videos (id) on delete cascade,
  owner_id uuid references public.users (id) on delete set null,
  kind text not null check (kind in ('process', 'dub', 'revoice', 'rerender', 'retrain')),
  status text not null default 'queued'
    check (status in ('queued', 'running', 'done', 'failed', 'needs_credits', 'superseded')),
  stage text,
  progress int not null default 0,
  error text,
  logs jsonb not null default '[]',
  stages jsonb not null default '[]',
  params jsonb,                   -- providers and options only, never keys
  queue text,
  key_source text check (key_source in ('platform', 'user', 'none')),
  cost jsonb,                     -- estimated audio minutes, characters, INR
  superseded_by uuid,
  started_at timestamptz,
  finished_at timestamptz,
  updated_at timestamptz default now(),
  created_at timestamptz not null default now()
);
create index if not exists jobs_video_idx on public.jobs (video_id, created_at desc);
create index if not exists jobs_platform_idx on public.jobs (key_source, created_at);

-- New Google sign-ins get a profile row and a free plan.
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.users (id, email, name, avatar_url)
  values (new.id, coalesce(new.email, ''),
          coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'name', split_part(new.email, '@', 1)),
          new.raw_user_meta_data ->> 'avatar_url')
  on conflict (id) do nothing;
  insert into public.user_plans (user_id) values (new.id) on conflict (user_id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

insert into public.model_versions (version, path, metrics, active)
values (1, 'bundle', '{"note": "trained bundle from kaushaldub_train.ipynb"}', true)
on conflict (version) do nothing;
