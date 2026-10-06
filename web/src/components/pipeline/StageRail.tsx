import clsx from "clsx";
import {
  BookOpen,
  Check,
  Clapperboard,
  Film,
  Flag,
  Images,
  ListTree,
  Loader2,
  Mic,
  Palette,
  ScanSearch,
  Scissors,
  X,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import type { Stage } from "../../lib/api";
import { ENGINE, EngineTag, StatusPill } from "../ui";

const ICONS: Record<string, LucideIcon> = {
  story: BookOpen,
  analysis: ScanSearch,
  plan: ListTree,
  sheets: Palette,
  keyframes: Images,
  voice: Mic,
  render: Clapperboard,
  assemble: Scissors,
  film: Film,
};

const DONE = new Set(["done", "skipped"]);

export function StageRail({
  stages,
  selected,
  onSelect,
}: {
  stages: Stage[];
  selected: string | null;
  onSelect: (key: string) => void;
}) {
  return (
    <div className="overflow-x-auto pb-1">
      <ol className="flex min-w-[1080px] items-stretch">
        {stages.map((stage, i) => {
          const Icon = ICONS[stage.key] ?? Film;
          const next = stages[i + 1];
          const flowing = stage.status === "running";
          const reached = DONE.has(stage.status);
          return (
            <li key={stage.key} className="relative flex min-w-0 flex-1 flex-col items-center">
              {next && (
                <span
                  aria-hidden
                  className={clsx(
                    "absolute top-[22px] left-[calc(50%+26px)] h-[2px] w-[calc(100%-52px)] rounded-full",
                    reached && DONE.has(next.status) && "bg-gradient-to-r from-ok/50 to-ok/30",
                    reached && !DONE.has(next.status) && "bg-gradient-to-r from-ok/40 to-white/10",
                    !reached && !flowing && "bg-white/[0.07]",
                    flowing &&
                      "animate-shimmer bg-[linear-gradient(90deg,rgb(243_169_60/0.15),rgb(243_169_60/0.8),rgb(243_169_60/0.15))] bg-[length:200%_100%]",
                  )}
                />
              )}
              <button
                onClick={() => onSelect(stage.key)}
                className={clsx(
                  "group relative flex w-full flex-col items-center rounded-xl px-1.5 pt-0 pb-2.5 text-center transition-colors",
                  selected === stage.key ? "bg-white/[0.035]" : "hover:bg-white/[0.025]",
                )}
              >
                <StageNode status={stage.status} engine={stage.engine} icon={Icon} />
                <div className="mt-2.5 flex items-center gap-1 text-[12.5px] leading-tight font-medium text-fg">
                  {stage.label}
                  {stage.checkpoint && (
                    <Flag className="size-3 shrink-0 text-warn" aria-label="needs your approval" />
                  )}
                </div>
                <div className="mt-1 max-w-full truncate px-1 text-[11px] text-fg-3">{stage.owner}</div>
                {stage.engine !== "user" && <EngineTag engine={stage.engine} className="mt-1 justify-center" />}
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function StageNode({ status, engine, icon: Icon }: { status: Stage["status"]; engine: Stage["engine"]; icon: LucideIcon }) {
  const color = ENGINE[engine].color;
  return (
    <div className="relative">
      <div
        className={clsx(
          "flex size-11 items-center justify-center rounded-2xl border transition-all",
          status === "done" && "border-ok/30 bg-ok/[0.08] text-fg",
          status === "skipped" && "border-dashed border-white/[0.12] bg-transparent text-fg-4",
          status === "pending" && "border-white/[0.08] bg-ink-800 text-fg-3",
          status === "queued" && "border-info/30 bg-info/[0.08] text-info",
          (status === "running" || status === "awaiting_approval") && "border-amber/50 bg-amber/[0.1] text-amber",
          status === "failed" && "border-bad/40 bg-bad/[0.1] text-bad",
        )}
        style={status === "running" ? { boxShadow: `0 0 0 4px rgb(243 169 60 / 0.08), 0 0 24px -4px ${color}` } : undefined}
      >
        <Icon className="size-[19px]" strokeWidth={1.7} />
      </div>
      <span
        className={clsx(
          "absolute -right-1.5 -bottom-1.5 flex size-[18px] items-center justify-center rounded-full border-2 border-ink-900",
          status === "done" && "bg-ok text-ink-950",
          status === "running" && "bg-amber text-ink-950",
          status === "failed" && "bg-bad text-ink-950",
          status === "awaiting_approval" && "bg-warn text-ink-950",
          !["done", "running", "failed", "awaiting_approval"].includes(status) && "hidden",
        )}
      >
        {status === "done" && <Check className="size-2.5" strokeWidth={3.5} />}
        {status === "running" && <Loader2 className="size-2.5 animate-spin" strokeWidth={3} />}
        {status === "failed" && <X className="size-2.5" strokeWidth={3.5} />}
        {status === "awaiting_approval" && <Flag className="size-2.5" strokeWidth={3} />}
      </span>
    </div>
  );
}

export function StageDetail({ stage, children }: { stage: Stage; children?: ReactNode }) {
  return (
    <div className="card animate-rise flex flex-col gap-4 p-5 md:flex-row md:items-start">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-[15px] font-semibold text-fg">{stage.label}</h3>
          <StatusPill status={stage.status} />
          {stage.checkpoint && (
            <span className="inline-flex items-center gap-1 text-[11px] text-warn">
              <Flag className="size-3" /> Approval checkpoint
            </span>
          )}
        </div>
        <p className="mt-1.5 text-[13px] leading-relaxed text-fg-2">{stage.detail}</p>
        {children && <div className="mt-3 text-[13px] text-fg-2">{children}</div>}
      </div>
      <dl className="grid shrink-0 grid-cols-2 gap-x-6 gap-y-2 text-[12px] md:w-[300px]">
        <dt className="text-fg-3">Owner</dt>
        <dd className="truncate text-fg">{stage.owner}</dd>
        {stage.engine !== "user" && (
          <>
            <dt className="text-fg-3">Engine</dt>
            <dd>
              <EngineTag engine={stage.engine} />
            </dd>
          </>
        )}
        {stage.model && (
          <>
            <dt className="text-fg-3">Model</dt>
            <dd className="truncate font-mono text-[11px] text-fg-2">{stage.model}</dd>
          </>
        )}
      </dl>
    </div>
  );
}
