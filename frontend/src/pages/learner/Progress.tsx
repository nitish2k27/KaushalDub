import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ago, fmt, LNE } from "@/lib/format";
import type { Ticket } from "@/lib/types";
import { Card, ErrorBox, Kpi, Loading, Pill, Progress as Bar, StatusPill } from "@/components/ui/primitives";

interface History {
  items: { video_id: string; title: string; progress: number; updated_at: string; quiz: string | null }[];
  videos_watched: number; quizzes_taken: number; preferred_lang: string | null;
}

export default function Progress() {
  const h = useQuery({ queryKey: ["history"], queryFn: () => api<History>("/me/history") });
  const t = useQuery({ queryKey: ["mytickets"], queryFn: () => api<(Ticket & { video_title: string })[]>("/me/tickets") });
  return (
    <div className="stack">
      <h2>My progress</h2>
      {h.isLoading && <Loading />}
      <ErrorBox error={h.error || t.error} />
      <div className="kpis">
        <Kpi value={h.data?.videos_watched ?? "–"} label="Videos watched" />
        <Kpi value={h.data?.quizzes_taken ?? "–"} label="Quizzes taken" />
        <Kpi value={h.data?.preferred_lang ? LNE[h.data.preferred_lang] : "–"} label="Preferred language" />
      </div>
      <Card>
        <h3 style={{ marginBottom: 10 }}>History</h3>
        <div className="tw"><table>
          <thead><tr><th>Video</th><th>When</th><th>Watched</th><th>Quiz</th></tr></thead>
          <tbody>
            {h.data?.items.length === 0 && <tr><td colSpan={4} className="muted">Nothing yet. <Link to="/l">Open the library</Link>.</td></tr>}
            {h.data?.items.map((x) => (
              <tr key={x.video_id}>
                <td><Link to={`/l/watch/${x.video_id}`}><b>{x.title}</b></Link></td>
                <td className="muted">{ago(x.updated_at)}</td>
                <td><Bar value={x.progress} className="w-[100px]" label={`${Math.round(x.progress)}% watched`} /></td>
                <td>{x.quiz || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </Card>
      <Card>
        <h3 style={{ marginBottom: 10 }}>My reports</h3>
        <div className="tw"><table>
          <thead><tr><th>Video</th><th>At</th><th>Issue</th><th>Status</th><th>Trainer’s reply</th></tr></thead>
          <tbody>
            {t.data?.length === 0 && <tr><td colSpan={5} className="muted">You have not reported anything.</td></tr>}
            {t.data?.map((x) => (
              <tr key={x.id}>
                <td><b>{x.video_title}</b><br /><span className="tiny muted">{LNE[x.lang]} · {ago(x.created_at)}</span></td>
                <td>{fmt(x.timestamp_s)}</td>
                <td><Pill tone="gray">{x.category}</Pill><br /><span className="small">{x.message}</span></td>
                <td><StatusPill status={x.status} /></td>
                <td className="small">{x.reply || <span className="muted">No reply yet</span>}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </Card>
    </div>
  );
}
