import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Engine, JobStatus, ShotStatus, StageStatus } from "../lib/api";

// ---------------------------------------------------------------- buttons

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-amber text-ink-950 hover:bg-amber-hi shadow-[0_8px_24px_-10px_rgb(243_169_60/0.7)] disabled:bg-ink-600 disabled:text-fg-3 disabled:shadow-none",
  secondary: "bg-ink-750 text-fg border border-white/[0.08] hover:bg-ink-700 hover:border-white/[0.12] disabled:text-fg-4",
  ghost: "text-fg-2 hover:text-fg hover:bg-white/[0.05] disabled:text-fg-4",
  danger: "bg-bad/10 text-bad border border-bad/30 hover:bg-bad/20 disabled:opacity-50",
};

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  loading,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: "sm" | "md" | "lg";
  icon?: ReactNode;
  loading?: boolean;
}) {
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition-all duration-150 select-none disabled:cursor-not-allowed",
        size === "sm" && "h-8 px-3 text-[12.5px]",
        size === "md" && "h-9 px-3.5 text-[13px]",
        size === "lg" && "h-11 px-5 text-[14px]",
        VARIANTS[variant],
        className,
      )}
      disabled={loading || rest.disabled}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function IconButton({
  label,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      aria-label={label}
      title={label}
      className={clsx(
        "inline-flex size-8 items-center justify-center rounded-lg text-fg-2 transition-colors hover:bg-white/[0.06] hover:text-fg",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------- status

type AnyStatus = StageStatus | JobStatus | ShotStatus | "interrupted";
const STATUS: Record<string, { label: string; tone: string; live?: boolean }> = {
  pending: { label: "Pending", tone: "text-fg-3 bg-white/[0.04] border-white/[0.07]" },
  queued: { label: "Queued", tone: "text-info bg-info/10 border-info/25" },
  running: { label: "Running", tone: "text-amber bg-amber/10 border-amber/30", live: true },
  rendering: { label: "Rendering", tone: "text-amber bg-amber/10 border-amber/30", live: true },
  checking: { label: "Checking", tone: "text-amber bg-amber/10 border-amber/30", live: true },
  cancelling: { label: "Cancelling", tone: "text-warn bg-warn/10 border-warn/30", live: true },
  awaiting_approval: { label: "Needs approval", tone: "text-warn bg-warn/10 border-warn/30" },
  needs_review: { label: "Needs review", tone: "text-warn bg-warn/10 border-warn/30" },
  done: { label: "Done", tone: "text-ok bg-ok/10 border-ok/25" },
  succeeded: { label: "Succeeded", tone: "text-ok bg-ok/10 border-ok/25" },
  skipped: { label: "Skipped", tone: "text-fg-4 bg-transparent border-white/[0.07] border-dashed" },
  failed: { label: "Failed", tone: "text-bad bg-bad/10 border-bad/30" },
  cancelled: { label: "Cancelled", tone: "text-fg-3 bg-white/[0.04] border-white/[0.07]" },
};

export function StatusPill({ status, label, className }: { status: AnyStatus; label?: string; className?: string }) {
  const s = STATUS[status] ?? STATUS.pending;
  return (
    <span
      className={clsx(
        "inline-flex h-[22px] items-center gap-1.5 rounded-full border px-2 text-[11px] font-medium whitespace-nowrap",
        s.tone,
        className,
      )}
    >
      <span className={clsx("size-1.5 rounded-full bg-current", s.live && "animate-pulse-soft")} />
      {label ?? s.label}
    </span>
  );
}

export const ENGINE: Record<Engine, { label: string; color: string; text: string }> = {
  claude: { label: "Claude", color: "var(--color-engine-claude)", text: "text-engine-claude" },
  openai: { label: "OpenAI", color: "var(--color-engine-openai)", text: "text-engine-openai" },
  ltx: { label: "LTX · local", color: "var(--color-engine-ltx)", text: "text-engine-ltx" },
  ffmpeg: { label: "ffmpeg", color: "var(--color-engine-ffmpeg)", text: "text-engine-ffmpeg" },
  user: { label: "You", color: "var(--color-engine-user)", text: "text-engine-user" },
};

export function EngineTag({ engine, model, className }: { engine: Engine; model?: string; className?: string }) {
  const e = ENGINE[engine];
  return (
    <span className={clsx("inline-flex min-w-0 items-center gap-1.5 text-[11px] text-fg-3", className)}>
      <span className="size-1.5 shrink-0 rounded-[2px]" style={{ background: e.color }} />
      <span className={clsx("font-medium", e.text)}>{e.label}</span>
      {model && <span className="truncate font-mono text-[10.5px] text-fg-4">{model}</span>}
    </span>
  );
}

// ---------------------------------------------------------------- QA scores

// Gates mirror storyvid/pipeline.py: words WER ≤ 0.2, voice ≥ 0.78, continuity ≥ 0.72. Identity only ranks takes.
export type Metric = "words" | "voice" | "identity" | "continuity";
export function metricTone(metric: Metric, value: number): "ok" | "bad" | "fair" {
  if (metric === "words") return value <= 0.2 ? "ok" : "bad";
  if (metric === "voice") return value >= 0.78 ? "ok" : "bad";
  if (metric === "continuity") return value >= 0.72 ? "ok" : "bad";
  return value >= 0.8 ? "ok" : value >= 0.7 ? "fair" : "bad";
}

const METRIC_LABEL: Record<Metric, string> = { words: "Words", voice: "Voice", identity: "Look", continuity: "Flow" };

export function ScoreChip({ metric, value, compact }: { metric: Metric; value: number | null; compact?: boolean }) {
  if (value == null) return null;
  const tone = metricTone(metric, value);
  const shown = metric === "words" ? (value === 0 ? "✓" : `${Math.round(value * 100)}%`) : value.toFixed(2);
  return (
    <span
      title={metric === "words" ? `Word error rate ${value}` : `${METRIC_LABEL[metric]} similarity ${value}`}
      className={clsx(
        "inline-flex h-[22px] items-center gap-1 rounded-md border px-1.5 font-mono text-[10.5px]",
        tone === "ok" && "border-ok/20 bg-ok/[0.07] text-ok",
        tone === "fair" && "border-warn/20 bg-warn/[0.07] text-warn",
        tone === "bad" && "border-bad/25 bg-bad/[0.08] text-bad",
      )}
    >
      {!compact && <span className="font-sans text-[10.5px] text-fg-3">{METRIC_LABEL[metric]}</span>}
      {shown}
    </span>
  );
}

// ---------------------------------------------------------------- misc

export function ProgressBar({ value, live, className }: { value: number; live?: boolean; className?: string }) {
  return (
    <div className={clsx("relative h-1.5 overflow-hidden rounded-full bg-white/[0.06]", className)}>
      <div
        className={clsx(
          "absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-amber-lo to-amber transition-[width] duration-700",
          live && "after:absolute after:inset-0 after:animate-shimmer after:bg-[linear-gradient(90deg,transparent,rgb(255_255_255/0.35),transparent)] after:bg-[length:200%_100%]",
        )}
        style={{ width: `${Math.min(100, Math.max(value, live ? 3 : 0))}%` }}
      />
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  children,
  action,
  className,
}: {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("flex flex-col items-center justify-center px-6 py-14 text-center", className)}>
      <div className="mb-4 flex size-12 items-center justify-center rounded-2xl border border-white/[0.08] bg-ink-800 text-fg-3">
        {icon}
      </div>
      <h3 className="text-[15px] font-semibold text-fg">{title}</h3>
      {children && <p className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-fg-3">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function SectionTitle({ eyebrow, title, right }: { eyebrow?: string; title: string; right?: ReactNode }) {
  return (
    <div className="mb-3 flex items-end justify-between gap-4">
      <div>
        {eyebrow && <div className="eyebrow mb-1">{eyebrow}</div>}
        <h2 className="text-[15px] font-semibold tracking-tight text-fg">{title}</h2>
      </div>
      {right}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="eyebrow">{label}</div>
      <div className="mt-1 truncate font-display text-[22px] leading-tight font-medium text-fg">{value}</div>
      {hint && <div className="mt-0.5 truncate text-[11.5px] text-fg-3">{hint}</div>}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-white/10 bg-ink-700 px-1 font-mono text-[10px] text-fg-2">
      {children}
    </kbd>
  );
}
