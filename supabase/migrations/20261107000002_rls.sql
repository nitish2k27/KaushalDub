-- Row-level security. The FastAPI backend uses the service role (bypasses RLS) and checks ownership itself;
-- these policies protect the data if the browser ever talks to Supabase directly with a user's JWT.

create or replace function public.my_role() returns text
language sql stable security definer set search_path = public as $$
  select role from public.users where id = auth.uid()
$$;

create or replace function public.can_view_video(v uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.videos x
    where x.id = v
      and (x.owner = auth.uid() or x.published
           or (public.my_role() = 'annotator' and x.status in ('review', 'ready')))
  )
$$;

create or replace function public.owns_video(v uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.videos x where x.id = v and x.owner = auth.uid())
$$;

alter table public.users enable row level security;
alter table public.videos enable row level security;
alter table public.steps enable row level security;
alter table public.translations enable row level security;
alter table public.outputs enable row level security;
alter table public.tts_clips enable row level security;
alter table public.quizzes enable row level security;
alter table public.quiz_attempts enable row level security;
alter table public.watch_history enable row level security;
alter table public.tickets enable row level security;
alter table public.annotations enable row level security;
alter table public.annotation_requests enable row level security;
alter table public.correction_memory enable row level security;
alter table public.model_versions enable row level security;
alter table public.user_plans enable row level security;
alter table public.user_api_keys enable row level security;
alter table public.jobs enable row level security;

-- users: everyone signed in can read names (shown as "by ..."); each user edits only their own row.
create policy users_read on public.users for select to authenticated using (true);
create policy users_update_self on public.users for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());

-- videos
create policy videos_read on public.videos for select to authenticated using (public.can_view_video(id));
create policy videos_insert on public.videos for insert to authenticated
  with check (owner = auth.uid() and public.my_role() = 'trainer');
create policy videos_update on public.videos for update to authenticated
  using (owner = auth.uid()) with check (owner = auth.uid());
create policy videos_delete on public.videos for delete to authenticated using (owner = auth.uid());

-- per-video children: readable when the video is, writable by its owner
create policy steps_read on public.steps for select to authenticated using (public.can_view_video(video_id));
create policy steps_write on public.steps for all to authenticated
  using (public.owns_video(video_id)) with check (public.owns_video(video_id));
create policy translations_read on public.translations for select to authenticated using (public.can_view_video(video_id));
create policy translations_write on public.translations for all to authenticated
  using (public.owns_video(video_id)) with check (public.owns_video(video_id));
create policy outputs_read on public.outputs for select to authenticated using (public.can_view_video(video_id));
create policy quizzes_read on public.quizzes for select to authenticated using (public.can_view_video(video_id));
create policy quizzes_write on public.quizzes for all to authenticated
  using (public.owns_video(video_id)) with check (public.owns_video(video_id));
create policy tts_read on public.tts_clips for select to authenticated using (public.owns_video(video_id));

-- learner data: own rows only
create policy attempts_own on public.quiz_attempts for select to authenticated using (user_id = auth.uid());
create policy attempts_insert on public.quiz_attempts for insert to authenticated
  with check (user_id = auth.uid() and public.can_view_video(video_id));
create policy history_own on public.watch_history for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

-- tickets: the reporter and the video's trainer
create policy tickets_read on public.tickets for select to authenticated
  using (reporter_id = auth.uid() or trainer_id = auth.uid());
create policy tickets_insert on public.tickets for insert to authenticated
  with check (reporter_id = auth.uid() and public.my_role() = 'learner' and public.can_view_video(video_id));
create policy tickets_trainer_update on public.tickets for update to authenticated
  using (trainer_id = auth.uid()) with check (trainer_id = auth.uid());

-- annotations: annotator's own drafts; requests visible to both sides, decided by the trainer
create policy annotations_own on public.annotations for all to authenticated
  using (annotator = auth.uid()) with check (annotator = auth.uid() and public.my_role() = 'annotator');
create policy annreq_read on public.annotation_requests for select to authenticated
  using (annotator_id = auth.uid() or trainer_id = auth.uid());
create policy annreq_insert on public.annotation_requests for insert to authenticated
  with check (annotator_id = auth.uid() and public.my_role() = 'annotator');
create policy annreq_decide on public.annotation_requests for update to authenticated
  using (trainer_id = auth.uid()) with check (trainer_id = auth.uid());

-- model learning: read-only for signed-in users; only the backend writes
create policy memory_read on public.correction_memory for select to authenticated using (true);
create policy versions_read on public.model_versions for select to authenticated using (true);

-- plans: read your own; changes go through the API so the quota rules cannot be bypassed
create policy plans_read on public.user_plans for select to authenticated using (user_id = auth.uid());

-- user_api_keys: RLS on and NO policies: browsers can never read encrypted keys. Backend only.

-- jobs: owners can watch progress
create policy jobs_read on public.jobs for select to authenticated using (owner_id = auth.uid());
