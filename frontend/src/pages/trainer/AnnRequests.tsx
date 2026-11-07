import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import type { AnnRequest, Job } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card, ErrorBox, Kpi, Loading, Pill, Progress, StatusPill } from "@/components/ui/primitives";

interface ModelStatus {
  active_version: number; pending: number; memory: number; threshold: number; last_retrain: string | null;
  running_job: Job | null; last_job: Job | null;
  versions: { version: number; active: boolean; created_at: string; metrics: { test_macro_f1?: number | null; previous_macro_f1?: number | null; decision?: string; note?: string } | null }[];
}

export default function AnnRequests() {
  const qc = useQueryClient();
  const toast = useToast();
  const reqs = useQuery({ queryKey: ["annreq", "all"], queryFn: () => api<AnnRequest[]>("/annotation-requests") });
  const model = useQuery({ queryKey: ["model"], queryFn: () => api<ModelStatus>("/model/status"),
    refetchInterval: (q) => (q.state.data?.running_job ? 3000 : false) });
  const L = model.data;
  const retrain = async () => {
    try {
      await api("/model/retrain", { method: "POST" });
      toast("Retraining started");
      qc.invalidateQueries({ queryKey: ["model"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not start retraining");
    }
  };
  return (
    <div className="stack">
      <div><h2>Annotation requests</h2><p className="muted small">Annotators correct the model’s step labels. Approve a correction to apply it to the video and teach the model; send it back if it is wrong.</p></div>
      <Card>
        {reqs.isLoading && <Loading />}
        <ErrorBox error={reqs.error} />
        <div className="tw">
          <table>
            <thead><tr><th>Clip</th><th>From</th><th>Changes</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {reqs.data?.length === 0 && <tr><td colSpan={5} className="muted">No corrections yet.</td></tr>}
              {reqs.data?.map((r) => (
                <tr key={r.id}>
                  <td><b>{r.video_title}</b><br /><span className="tiny muted">{ago(r.created_at)}</span></td>
                  <td className="small">{r.annotator_name}</td>
                  <td>{r.changes.length}</td>
                  <td><StatusPill status={r.status} /></td>
                  <td><Link className={`btn sm ${r.status === "pending" ? "pri" : ""}`} to={`/t/annotations/${r.id}`}>{r.status === "pending" ? "Review" : "View"}</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card className="stack" style={{ gap: 12 }}>
        <div className="row"><h3>Model learning</h3><span className="grow" /><Pill>Step model v{L?.active_version ?? "–"}</Pill></div>
        <div className="kpis">
          <Kpi value={L?.pending ?? "–"} label="Approved corrections waiting for retraining" />
          <Kpi value={L?.memory ?? "–"} label="Corrections in memory" />
          <Kpi value={L?.last_retrain ? ago(L.last_retrain) : "Never"} label="Last retrained" />
        </div>
        <p className="small muted">
          This is human-in-the-loop active learning (not reinforcement learning). An approved correction fixes that video straight away and goes into the
          correction memory for its skill, so the next video of the same skill is checked against it. Once {L?.threshold ?? 20} corrections are waiting,
          the model is retrained, and the new version replaces the old one only if it scores at least as well (macro-F1) on the test videos.
        </p>
        {L?.running_job && (
          <div className="stack" style={{ gap: 6 }}>
            <span className="small">Retraining: {L.running_job.stages.find((s) => s.status === "run")?.label || "queued"}</span>
            <Progress value={L.running_job.progress} label="Retraining progress" />
          </div>
        )}
        {L?.last_job?.status === "failed" && <ErrorBox error={`Last retrain failed: ${L.last_job.error}`} />}
        <div className="row"><Button onClick={retrain} disabled={!L?.pending || !!L?.running_job}>Retrain now</Button></div>
        {L && L.versions.length > 1 && (
          <div className="tw">
            <table>
              <thead><tr><th>Version</th><th>Test macro-F1</th><th>Decision</th><th>When</th></tr></thead>
              <tbody>
                {L.versions.map((v) => (
                  <tr key={v.version}>
                    <td>v{v.version} {v.active && <Pill tone="good">Active</Pill>}</td>
                    <td>{v.metrics?.test_macro_f1 != null ? v.metrics.test_macro_f1.toFixed(1) : "–"}{v.metrics?.previous_macro_f1 != null && <span className="tiny muted"> (was {v.metrics.previous_macro_f1.toFixed(1)})</span>}</td>
                    <td className="small">{v.metrics?.decision || v.metrics?.note || ""}</td>
                    <td className="muted small">{ago(v.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
