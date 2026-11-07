import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";
import { Icon } from "@/components/Icon";
import { ROLE } from "@/components/Shell";
import { ErrorBox, Pill } from "@/components/ui/primitives";

const ROLES: { r: Role; title: string; sub: string; items: string[] }[] = [
  { r: "trainer", title: "Trainer", sub: "Upload a demonstration and publish a dubbed version.",
    items: ["Upload and process video", "Review steps and captions", "Answer learner reports and annotator corrections"] },
  { r: "learner", title: "Learner", sub: "Find a skill video, watch it in your language, test yourself.",
    items: ["Search the library", "Follow steps with narration", "Take the quiz", "Report a problem at any moment"] },
  { r: "annotator", title: "Annotator", sub: "Label step boundaries to train the step recogniser.",
    items: ["Check model suggestions", "Split and relabel segments", "Send corrections to the trainer for approval"] },
];

export default function RolePicker() {
  const { user, loading, setRole } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [err, setErr] = useState<unknown>(null);
  const switching = params.get("switch") === "1";

  useEffect(() => {
    if (!loading && user && !switching) nav(ROLE[user.role].home, { replace: true });
  }, [loading, user, switching, nav]);

  const pick = async (r: Role) => {
    setErr(null);
    if (user) {
      try {
        await setRole(r);
        nav(ROLE[r].home);
      } catch (e) {
        setErr(e);
      }
    } else nav(`/login?role=${r}`);
  };

  return (
    <div className="wrap">
      <div className="hero">
        <Pill tone="warn">RV University · CS3235</Pill>
        <h1 style={{ marginTop: 12 }}>Skill videos in the language people work in</h1>
        <p>KaushalDub turns a short how-to video into numbered steps, editable captions, a narrated version in Kannada or Hindi, and a quiz. Choose how you want to use it.</p>
      </div>
      <ErrorBox error={err} />
      <div className="roles">
        {ROLES.map((x) => (
          <button key={x.r} className="role" onClick={() => pick(x.r)}>
            <span className="ico"><Icon name={ROLE[x.r].i} /></span>
            <h2>{x.title}</h2>
            <p className="muted">{x.sub}</p>
            <ul>{x.items.map((i) => <li key={i}>{i}</li>)}</ul>
            {user?.role === x.r && <Pill tone="good">Current role</Pill>}
          </button>
        ))}
      </div>
      <p className="tiny muted" style={{ padding: "32px 0 24px" }}>Sign in with Google. You can switch role at any time from the top bar.</p>
    </div>
  );
}
