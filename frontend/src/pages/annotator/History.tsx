import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { Card, ErrorBox, Loading, StatusPill } from "@/components/ui/primitives";

interface Row { clip_id: string; title: string; status: string; segments: number; updated_at: string; reviewer_note: string | null; trainer: string }

export default function History() {
  const q = useQuery({ queryKey: ["mylabels"], queryFn: () => api<Row[]>("/me/annotations") });
  return (
    <div className="stack">
      <div><h2>My labels</h2><p className="muted small">Submitted corrections go to the video’s trainer. Approved ones fix the video and teach the model.</p></div>
      <Card>
        {q.isLoading && <Loading />}
        <ErrorBox error={q.error} />
        <div className="tw"><table>
          <thead><tr><th>Clip</th><th>Segments</th><th>When</th><th>Review</th><th>Note</th></tr></thead>
          <tbody>
            {q.data?.length === 0 && <tr><td colSpan={5} className="muted">No labels yet.</td></tr>}
            {q.data?.map((h) => (
              <tr key={h.clip_id}>
                <td><b>{h.title}</b><br /><span className="tiny muted">Trainer: {h.trainer}</span></td>
                <td>{h.segments}</td>
                <td className="muted">{ago(h.updated_at)}</td>
                <td><StatusPill status={h.status} /></td>
                <td className="small">{h.reviewer_note || ""}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </Card>
    </div>
  );
}
