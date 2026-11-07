import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ago, fmt, LNE } from "@/lib/format";
import type { Ticket } from "@/lib/types";
import { Card, Chip, ErrorBox, Loading, Pill, StatusPill } from "@/components/ui/primitives";

export default function Reports() {
  const [f, setF] = useState<"open" | "closed" | "all">("open");
  const q = useQuery({ queryKey: ["tickets", f], queryFn: () => api<Ticket[]>("/tickets", { query: { status: f } }) });
  return (
    <div className="stack">
      <div><h2>Learner reports</h2><p className="muted small">Learners mark a moment in a video and say what felt wrong. Open a report to jump to that moment, fix the step, reply and close it.</p></div>
      <div className="chips">{(["open", "closed", "all"] as const).map((c) => <Chip key={c} on={c === f} onClick={() => setF(c)}>{c[0].toUpperCase() + c.slice(1)}</Chip>)}</div>
      <Card>
        {q.isLoading && <Loading />}
        <ErrorBox error={q.error} />
        <div className="tw">
          <table>
            <thead><tr><th>Video</th><th>At</th><th>What felt wrong</th><th>From</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {q.data?.length === 0 && <tr><td colSpan={6} className="muted">No reports here.</td></tr>}
              {q.data?.map((t) => (
                <tr key={t.id}>
                  <td><b>{t.video_title}</b><br /><span className="tiny muted">{LNE[t.lang]} version · {ago(t.created_at)}</span></td>
                  <td>{fmt(t.timestamp_s)}</td>
                  <td><Pill tone="gray">{t.category}</Pill><br /><span className="small">{t.message}</span></td>
                  <td className="small">{t.reporter_name}</td>
                  <td><StatusPill status={t.status} /></td>
                  <td><Link className={`btn sm ${t.status === "open" ? "pri" : ""}`} to={`/t/reports/${t.id}`}>{t.status === "open" ? "Review" : "View"}</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
