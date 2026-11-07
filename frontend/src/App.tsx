import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";
import { ROLE, Shell } from "@/components/Shell";
import { Loading } from "@/components/ui/primitives";
import RolePicker from "@/pages/RolePicker";
import Login from "@/pages/Login";
import TrainerHome from "@/pages/trainer/Home";
import Processing from "@/pages/trainer/Processing";
import Review from "@/pages/trainer/Review";
import Dubbing from "@/pages/trainer/Dubbing";
import Result from "@/pages/trainer/Result";
import Reports from "@/pages/trainer/Reports";
import TicketPage from "@/pages/trainer/Ticket";
import AnnRequests from "@/pages/trainer/AnnRequests";
import AnnReview from "@/pages/trainer/AnnReview";
import Settings from "@/pages/trainer/Settings";
import Library from "@/pages/learner/Library";
import Watch from "@/pages/learner/Watch";
import Quiz from "@/pages/learner/Quiz";
import Progress from "@/pages/learner/Progress";
import Queue from "@/pages/annotator/Queue";
import Label from "@/pages/annotator/Label";
import History from "@/pages/annotator/History";

function Guard({ role, children }: { role: Role; children: ReactNode }) {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <div className="wrap" style={{ paddingTop: 48 }}><Loading /></div>;
  if (!user) return <Navigate to={`/login?role=${role}&next=${encodeURIComponent(loc.pathname)}`} replace />;
  if (user.role !== role) return <Navigate to={ROLE[user.role].home} replace />;
  return <Shell>{children}</Shell>;
}

export default function App() {
  const T = (el: ReactNode) => <Guard role="trainer">{el}</Guard>;
  const L = (el: ReactNode) => <Guard role="learner">{el}</Guard>;
  const A = (el: ReactNode) => <Guard role="annotator">{el}</Guard>;
  return (
    <Routes>
      <Route path="/" element={<RolePicker />} />
      <Route path="/login" element={<Login />} />
      <Route path="/t" element={T(<TrainerHome />)} />
      <Route path="/t/videos/:id/processing" element={T(<Processing />)} />
      <Route path="/t/videos/:id/review" element={T(<Review />)} />
      <Route path="/t/videos/:id/dub" element={T(<Dubbing />)} />
      <Route path="/t/videos/:id/result" element={T(<Result />)} />
      <Route path="/t/reports" element={T(<Reports />)} />
      <Route path="/t/reports/:id" element={T(<TicketPage />)} />
      <Route path="/t/annotations" element={T(<AnnRequests />)} />
      <Route path="/t/annotations/:id" element={T(<AnnReview />)} />
      <Route path="/t/settings" element={T(<Settings />)} />
      <Route path="/l" element={L(<Library />)} />
      <Route path="/l/watch/:id" element={L(<Watch />)} />
      <Route path="/l/quiz/:id" element={L(<Quiz />)} />
      <Route path="/l/progress" element={L(<Progress />)} />
      <Route path="/a" element={A(<Queue />)} />
      <Route path="/a/label/:id" element={A(<Label />)} />
      <Route path="/a/history" element={A(<History />)} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
