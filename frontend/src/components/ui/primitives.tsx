import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { STATUS } from "@/lib/format";

// shadcn-style primitives mapped onto the mockup's component classes.

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(({ className, ...p }, ref) => (
  <div ref={ref} className={cn("card", className)} {...p} />
));
Card.displayName = "Card";

const pillVariants = cva("pill", {
  variants: { tone: { brand: "", warn: "warn", good: "good", bad: "bad", gray: "gray" } },
  defaultVariants: { tone: "brand" },
});
export function Pill({ className, tone, ...p }: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof pillVariants>) {
  return <span className={cn(pillVariants({ tone }), className)} {...p} />;
}

export function StatusPill({ status }: { status: string }) {
  const s = STATUS[status] || { text: status, tone: "gray" as const };
  return <Pill tone={s.tone || "brand"}>{s.text}</Pill>;
}

export function Chip({ on, className, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { on?: boolean }) {
  return <button type="button" className={cn("chip", on && "on", className)} aria-pressed={on} {...p} />;
}

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ type = "text", ...p }, ref) => (
  <input ref={ref} type={type} {...p} />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>((p, ref) => (
  <textarea ref={ref} {...p} />
));
Textarea.displayName = "Textarea";

export function Label({ className, ...p }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("l", className)} {...p} />;
}

export function Select({ options, ...p }: React.SelectHTMLAttributes<HTMLSelectElement> & { options: (string | { value: string; label: string; disabled?: boolean })[] }) {
  return (
    <select {...p}>
      {options.map((o) =>
        typeof o === "string" ? <option key={o} value={o}>{o}</option>
          : <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>)}
    </select>
  );
}

export function Progress({ value, className, label }: { value: number; className?: string; label?: string }) {
  return (
    <div className={cn("bar", className)} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value)} aria-label={label}>
      <i style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function Kpi({ value, label }: { value: React.ReactNode; label: string }) {
  return <div className="kpi"><b>{value}</b><span className="muted small">{label}</span></div>;
}

export function Badge({ n }: { n: number }) {
  return n ? <span className="cnt" aria-label={`${n} new`}>{n}</span> : null;
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="errbox small" role="alert">{error instanceof Error ? error.message : String(error)}</div>;
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <p className="muted small" role="status">{what}…</p>;
}
