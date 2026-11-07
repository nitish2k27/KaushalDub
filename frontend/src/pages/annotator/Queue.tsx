import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Card, ErrorBox, Kpi, Loading, Pill } from "@/components/ui/primitives";

interface QueueData {
  clips: { clip_id: string; title: string; domain: string; task: string; duration_s: number; low_conf: number; draft: boolean; sent_back: boolean }[];
  stats: { waiting: number; submitted: number; agreement: number | null };
}

export default function Queue() {
  const q = useQuery({ queryKey: ["annqueue"], queryFn: () => api<QueueData>("/annotations/queue") });
  const d = q.data;
  return (
    <div className="stack">
      <div><h2>Labelling queue</h2><p className="muted small">Check the model’s suggested step boundaries and fix what is wrong. Clips where the model was unsure come first.</p></div>
      <div className="kpis">
        <Kpi value={d?.stats.waiting ?? "–"} label="Clips waiting" />
        <Kpi value={d?.stats.submitted ?? "–"} label="Submitted" />
        <Kpi value={d?.stats.agreement != null ? `${d.stats.agreement}%` : "–"} label="Accepted by trainers" />
      </div>
      <Card>
        {q.isLoading && <Loading />}
        <ErrorBox error={q.error} />
        <div className="tw"><table>
          <thead><tr><th>Clip</th><th>Domain</th><th>Length</th><th>Model flags</th><th></th></tr></thead>
          <tbody>
            {d?.clips.length === 0 && <tr><td colSpan={5} className="muted">Nothing to label right now.</td></tr>}
            {d?.clips.map((c, i) => (
              <tr key={c.clip_id}>
                <td><b>{c.title}</b>{c.draft && <> <Pill tone="gray">Draft saved</Pill></>}{c.sent_back && <> <Pill tone="warn">Sent back</Pill></>}</td>
                <td>{c.domain}</td>
                <td>{fmt(c.duration_s)}</td>
                <td>{c.low_conf ? <Pill tone="warn">{c.low_conf} low confidence</Pill> : <Pill tone="gray">None</Pill>}</td>
                <td><Link className={`btn sm ${i === 0 ? "pri" : ""}`} to={`/a/label/${c.clip_id}`}>{c.draft ? "Continue" : "Start labelling"}</Link></td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </Card>
    </div>
  );
}
