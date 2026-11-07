import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useConfig } from "@/lib/hooks";
import { fmt, hue } from "@/lib/format";
import type { Video } from "@/lib/types";
import { DOMAIN_ICON, Icon } from "@/components/Icon";
import { Chip, ErrorBox, Input, Label, Loading, Pill } from "@/components/ui/primitives";

export default function Library() {
  const cfg = useConfig();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [domain, setDomain] = useState("All");
  useEffect(() => { const id = setTimeout(() => setQ(search), 250); return () => clearTimeout(id); }, [search]);
  const lib = useQuery({ queryKey: ["library", q, domain], queryFn: () => api<Video[]>("/library", { query: { q, domain: domain === "All" ? "" : domain } }) });
  return (
    <div className="stack">
      <div><h2>Skill video library</h2><p className="muted small">Pick a video and watch it with narration in your language.</p></div>
      <div className="row"><div className="grow" style={{ minWidth: 220 }}><Label htmlFor="srch">Search</Label>
        <Input type="search" id="srch" placeholder="Try “CPR”, “pizza” or “screen protector”" value={search} onChange={(e) => setSearch(e.target.value)} /></div></div>
      <div className="chips">{["All", ...(cfg.data?.domains || [])].map((c) => <Chip key={c} on={c === domain} onClick={() => setDomain(c)}>{c}</Chip>)}</div>
      {lib.isLoading && <Loading />}
      <ErrorBox error={lib.error} />
      <div className="lib">
        {lib.data?.length === 0 && <p className="muted">No videos match your search.</p>}
        {lib.data?.map((x) => (
          <Link key={x.id} className="vcard" to={`/l/watch/${x.id}`} style={{ color: "inherit", textDecoration: "none" }}>
            <div className="thumb" style={{ background: `hsl(${hue(x.domain || x.title)} 45% 32%)` }}>
              {x.thumb_url ? <><img src={x.thumb_url} alt="" loading="lazy" /><span className="ov" /></> : <Icon name={DOMAIN_ICON[x.domain] || "video"} className="" />}
              <span className="dur">{fmt(x.duration_s)}</span>
            </div>
            <div className="b">
              <b>{x.title}</b>
              <span className="small muted">{x.by} · {x.task_title}</span>
              <div className="row" style={{ gap: 6 }}><Pill tone="gray">{x.domain}</Pill>{x.langs.map((l) => <Pill key={l}>{l.toUpperCase()}</Pill>)}</div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
