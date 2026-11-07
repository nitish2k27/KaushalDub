-- Private storage buckets. The backend uploads with the service role and hands the browser short-lived
-- signed URLs, so no public read policy is needed.
insert into storage.buckets (id, name, public, file_size_limit)
values ('raw-videos', 'raw-videos', false, 314572800),
       ('outputs', 'outputs', false, 314572800),
       ('keyframes', 'keyframes', false, 10485760)
on conflict (id) do nothing;

-- A trainer may read their own raw uploads directly (path = <user id>/<video id>/source.ext).
create policy raw_videos_owner_read on storage.objects for select to authenticated
  using (bucket_id = 'raw-videos' and (storage.foldername(name))[1] = auth.uid()::text);
