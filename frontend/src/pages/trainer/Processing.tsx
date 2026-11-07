import { useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useVideo, videoRoute } from "@/lib/hooks";
import { JobProgress, Pipe } from "@/components/bits";
import { useToast } from "@/components/Toast";
import { ErrorBox, Loading } from "@/components/ui/primitives";

/** Used for both processing (stages 1-4) and dubbing (5-7): shows the latest job of the video. */
export function JobScreen({ step, title, sub }: { step: number; title: string; sub: (t: string) => string }) {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const v = useVideo(id);
  const onDone = useCallback(async () => {
    const fresh = await api<{ id: string; status: string }>(`/videos/${id}`);   // not the cache: status just changed
    qc.setQueryData(["video", id], fresh);
    qc.invalidateQueries({ queryKey: ["myvideos"] });
    nav(videoRoute(fresh), { replace: true });
  }, [id, nav, qc]);
  if (v.isLoading) return <Loading />;
  if (v.error || !v.data) return <ErrorBox error={v.error || "Video not found"} />;
  const job = v.data.job;
  const resume = job ? async () => {
    try {
      await api(`/jobs/${job.id}/resume`, { method: "POST" });
      await v.refetch();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not resume");
    }
  } : undefined;
  return (
    <>
      <Pipe n={step} />
      {job ? <JobProgress key={job.id} jobId={job.id} title={title} sub={sub(v.data.title)} onDone={onDone} onResume={resume} />
        : <Loading what="Waiting for the job" />}
    </>
  );
}

export default function Processing() {
  return <JobScreen step={1} title="Processing your video" sub={(t) => `${t} · this usually takes a few minutes.`} />;
}
