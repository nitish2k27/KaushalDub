import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { AppConfig, Plan, Video } from "./types";

export const useConfig = () => useQuery({ queryKey: ["config"], queryFn: () => api<AppConfig>("/config"), staleTime: Infinity });
export const usePlan = () => useQuery({ queryKey: ["plan"], queryFn: () => api<Plan>("/me/plan") });
export const useVideo = (id?: string, poll = false) =>
  useQuery({ queryKey: ["video", id], queryFn: () => api<Video>(`/videos/${id}`), enabled: !!id,
    refetchInterval: poll ? 3000 : false });

/** Where a trainer's video should open, by status. */
export function videoRoute(v: { id: string; status: string }) {
  if (["queued", "processing", "failed", "needs_credits"].includes(v.status)) return `/t/videos/${v.id}/processing`;
  if (v.status === "review") return `/t/videos/${v.id}/review`;
  if (v.status === "dubbing") return `/t/videos/${v.id}/dub`;
  return `/t/videos/${v.id}/result`;
}
