import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import { useVideo } from "@/lib/hooks";
import { LangBar } from "@/components/bits";
import { Button } from "@/components/ui/button";
import { Card, ErrorBox, Loading, Pill, Progress } from "@/components/ui/primitives";

export default function Quiz() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const v = useVideo(id);
  const [lang, setLang] = useState(params.get("lang") || "en");
  const [i, setI] = useState(0);
  const [picked, setPicked] = useState<number | null>(null);
  const [answers, setAnswers] = useState<number[]>([]);
  const [saveErr, setSaveErr] = useState<unknown>(null);
  if (v.isLoading) return <Loading />;
  if (v.error || !v.data?.quiz?.items.length) return <ErrorBox error={v.error || "This video has no quiz"} />;
  const quiz = v.data.quiz;
  const langs = v.data.langs.filter((l) => l === "en" || quiz.translations[l]);
  const Q = (lang !== "en" && quiz.translations[lang]) || quiz.items;
  const score = answers.filter((a, k) => a === quiz.items[k].answer).length;

  if (i >= Q.length) {
    const all = score === Q.length;
    return (
      <Card style={{ maxWidth: 560, margin: "0 auto", textAlign: "center" }}>
        <Pill tone={all ? "good" : "warn"}>Quiz complete</Pill>
        <h1 style={{ margin: "14px 0 6px" }}>{score} / {Q.length}</h1>
        <p className="muted">{all ? "You remembered every step in order." : "Watch the steps again to improve your score."}</p>
        <ErrorBox error={saveErr} />
        <div className="row" style={{ justifyContent: "center", marginTop: 20 }}>
          <Link className="btn" to={`/l/watch/${v.data.id}`}>Watch again</Link>
          <Link className="btn pri" to="/l/progress">See my progress</Link>
        </div>
      </Card>
    );
  }
  const q = Q[i];
  const answer = quiz.items[i].answer;
  const next = async () => {
    const a = [...answers, picked!];
    setAnswers(a);
    setPicked(null);
    if (i + 1 === Q.length) {
      try { await api(`/quiz/${v.data!.id}/attempts`, { body: { answers: a, lang } }); } catch (e) { setSaveErr(e); }
    }
    setI(i + 1);
  };
  return (
    <Card style={{ maxWidth: 640, margin: "0 auto" }}>
      <div className="row"><Pill>Question {i + 1} of {Q.length}</Pill><span className="grow" /><LangBar langs={langs} cur={lang} onPick={setLang} /></div>
      <Progress value={(i / Q.length) * 100} className="my-3.5" label="Quiz progress" />
      <h2 lang={lang}>{q.q}</h2>
      {q.options.map((o, j) => (
        <button key={j} className={`opt ${picked === null ? "" : j === answer ? "ok" : j === picked ? "no" : ""}`} disabled={picked !== null}
          onClick={() => setPicked(j)} lang={lang}><span className="n pill gray">{"ABCD"[j]}</span>{o}</button>
      ))}
      {picked !== null && (
        <div className="row" style={{ marginTop: 16 }} aria-live="polite">
          <Pill tone={picked === answer ? "good" : "bad"}>{picked === answer ? "Correct" : "Not quite"}</Pill>
          <span className="grow" /><Button variant="primary" onClick={next}>{i + 1 === Q.length ? "Finish" : "Next"}</Button>
        </div>
      )}
    </Card>
  );
}
