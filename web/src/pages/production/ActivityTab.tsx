import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, CircleDot, Clapperboard, Film, ScrollText, Square, TriangleAlert, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button, EmptyState, ScoreChip, StatusPill } from "../../components/ui";
import { api, type Job, type PipelineEvent, type Production } from "../../lib/api";
import { ago, duration, stamp } from "../../lib/format";

export function ActivityTab({ p, onCancel }: { p: Production; onCancel: () => void }) {
  const [jobId, setJobId] = useState<string | null>(null);
  const job = p.jobs.find((j) => j.id === jobId) ?? p.jobs[0];

  if (!p.jobs.length)
    return (
      <div className="card">
        <EmptyState icon={<ScrollText className="size-5" />} title="No jobs yet">
          Every render runs as a background job. Its progress, events and log show up here, and it keeps going even if you close the
          app.
        </EmptyState>
      </div>
    );

  return (
    <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
      <aside className="card h-fit overflow-hidden">
        <div className="border-b border-white/[0.06] px-4 py-3 text-[13px] font-medium text-fg">Jobs</div>
        <ul className="p-2">
          {p.jobs.map((j) => (
            <li key={j.id}>
              <button
                onClick={() => setJobId(j.id)}
                className={clsx(
                  "flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-left",
                  job?.id === j.id ? "bg-white/[0.05]" : "hover:bg-white/[0.03]",
                )}
              >
                <div className="min-w-0">
                  <div className="truncate font-mono text-[11.5px] text-fg-2">{j.id}</div>
                  <div className="mt-0.5 text-[11px] text-fg-4">
                    {j.kind} · {ago(j.created)}
                    {j.started && j.ended && ` · ${duration(j.ended - j.started)}`}
                  </div>
                </div>
                <StatusPill status={j.status} />
              </button>
            </li>
          ))}
        </ul>
      </aside>
      {job && <JobDetail job={job} onCancel={onCancel} />}
    </div>
  );
}

function JobDetail({ job, onCancel }: { job: Job; onCancel: () => void }) {
  const live = ["queued", "running", "cancelling"].includes(job.status);
  const events = useQuery({ queryKey: ["events", job.id], queryFn: () => api.jobEvents(job.id), refetchInterval: live ? 2500 : false });
  const log = useQuery({ queryKey: ["log", job.id], queryFn: () => api.jobLog(job.id, 400), refetchInterval: live ? 2500 : false });
  const logRef = useRef<HTMLPreElement>(null);
  useEffect(() => {
    const el = logRef.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 80) el.scrollTop = el.scrollHeight;
  }, [log.data]);

  const items = (events.data ?? []).filter((e) => ["run_started", "take_done", "shot_done", "film_done", "run_failed", "phase"].includes(e.type));
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <section className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="eyebrow">Render job</div>
            <div className="mt-1 flex items-center gap-2.5 font-mono text-[14px] text-fg">
              {job.id} <StatusPill status={job.status} />
            </div>
            <div className="mt-1 text-[12px] text-fg-3">
              Started {stamp(job.started)} {job.ended && `· ended ${stamp(job.ended)} · ${duration((job.ended ?? 0) - (job.started ?? 0))}`}
              {job.pid && live && ` · pid ${job.pid}`}
            </div>
          </div>
          {live && (
            <Button variant="danger" size="sm" icon={<Square className="size-3 fill-current" />} onClick={onCancel}>
              {job.status === "queued" ? "Remove from queue" : "Cancel"}
            </Button>
          )}
        </div>
        {job.error && (
          <div className="mt-4 flex gap-2 rounded-lg border border-bad/30 bg-bad/[0.07] px-3 py-2.5 text-[12.5px] text-bad">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" /> {job.error}
          </div>
        )}
      </section>

      <section className="card p-5">
        <div className="mb-3 text-[13px] font-medium text-fg">Timeline</div>
        {!items.length && <p className="text-[12.5px] text-fg-3">{live ? "Waiting for the first event…" : "This job ran before event logging existed."}</p>}
        <ol className="relative flex flex-col gap-0.5 before:absolute before:top-2 before:bottom-2 before:left-[11px] before:w-px before:bg-white/[0.07]">
          {items.map((e, i) => (
            <TimelineItem key={i} e={e} />
          ))}
        </ol>
      </section>

      <section className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-2.5">
          <span className="text-[13px] font-medium text-fg">Log</span>
          <span className="font-mono text-[10.5px] text-fg-4">{job.log}</span>
        </div>
        <pre ref={logRef} className="max-h-[360px] overflow-auto bg-ink-950/60 p-4 font-mono text-[11px] leading-relaxed text-fg-3">
          {log.data || "—"}
        </pre>
      </section>
    </div>
  );
}

function TimelineItem({ e }: { e: PipelineEvent }) {
  const time = <span className="ml-auto shrink-0 font-mono text-[10.5px] text-fg-4">{stamp(e.t)}</span>;
  const dot = (cls: string, icon: ReactNode) => (
    <span className={clsx("relative z-10 flex size-[23px] shrink-0 items-center justify-center rounded-full border-2 border-ink-850", cls)}>{icon}</span>
  );
  if (e.type === "take_done") {
    const passed = e.passed as boolean;
    return (
      <li className="flex items-center gap-3 py-1.5">
        {dot(passed ? "bg-ok/90 text-ink-950" : "bg-bad/90 text-ink-950", passed ? <Check className="size-3" strokeWidth={3} /> : <X className="size-3" strokeWidth={3} />)}
        <span className="text-[12.5px] text-fg">
          <span className="font-mono text-fg-2">{String(e.shot)}</span> take {(e.index as number) + 1}
          <span className="text-fg-4"> · {(e.cached as boolean) ? "cached" : duration(e.render_s as number)}</span>
        </span>
        <span className="flex flex-wrap gap-1">
          <ScoreChip metric="words" value={e.wer as number | null} compact />
          <ScoreChip metric="voice" value={e.voice as number | null} compact />
          <ScoreChip metric="identity" value={e.identity as number | null} compact />
          <ScoreChip metric="continuity" value={e.continuity as number | null} compact />
        </span>
        {!passed && <span className="truncate text-[11.5px] text-bad">{(e.failures as string[]).join(", ")}</span>}
        {time}
      </li>
    );
  }
  if (e.type === "shot_done")
    return (
      <li className="flex items-center gap-3 py-1.5">
        {dot("bg-ink-700 text-fg-2", <Clapperboard className="size-3" />)}
        <span className="text-[12.5px] text-fg-2">
          Shot <span className="font-mono">{String(e.shot)}</span> locked — take {(e.chosen as number) + 1} of {String(e.takes)}
          {(e.needs_review as boolean) && <span className="text-warn"> · needs review</span>}
        </span>
        {time}
      </li>
    );
  if (e.type === "film_done")
    return (
      <li className="flex items-center gap-3 py-1.5">
        {dot("bg-amber text-ink-950", <Film className="size-3" />)}
        <span className="text-[12.5px] font-medium text-fg">Film assembled · {duration(e.seconds as number)} of film in {duration(e.wall_s as number)}</span>
        {time}
      </li>
    );
  if (e.type === "run_failed")
    return (
      <li className="flex items-center gap-3 py-1.5">
        {dot("bg-bad text-ink-950", <X className="size-3" strokeWidth={3} />)}
        <span className="text-[12.5px] text-bad">{String(e.error)}</span>
        {time}
      </li>
    );
  return (
    <li className="flex items-center gap-3 py-1.5">
      {dot("bg-ink-700 text-fg-3", <CircleDot className="size-3" />)}
      <span className="text-[12.5px] text-fg-3">
        {e.type === "run_started" ? `Run started · ${(e.shots as unknown[]).length} shots` : `Phase: ${String(e.name).replace("_", " ")}`}
      </span>
      {time}
    </li>
  );
}
