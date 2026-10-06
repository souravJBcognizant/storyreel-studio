import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListChecks, Square } from "lucide-react";
import { Link } from "react-router";
import { PageHeader } from "../components/AppShell";
import { Button, EmptyState, ProgressBar, StatusPill } from "../components/ui";
import { api, type Job } from "../lib/api";
import { ago, duration, pct, stamp } from "../lib/format";

export function JobsPage() {
  const qc = useQueryClient();
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, refetchInterval: 3000 });
  const cancel = useMutation({ mutationFn: api.cancelJob, onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }) });
  const active = jobs.data?.filter((j) => ["queued", "running", "cancelling"].includes(j.status)) ?? [];
  const done = jobs.data?.filter((j) => !active.includes(j)) ?? [];

  return (
    <>
      <PageHeader
        eyebrow="Render engine"
        title="Jobs"
        subtitle="Renders run one at a time on this Mac's GPU, as background processes that survive restarts. Re-running a job resumes it: finished takes come from the cache."
      />
      <div className="flex flex-col gap-8 px-8 py-7">
        <section>
          <h2 className="eyebrow mb-3">Now</h2>
          {active.length ? (
            <div className="flex flex-col gap-3">
              {active.map((j) => (
                <ActiveJob key={j.id} job={j} onCancel={() => cancel.mutate(j.id)} />
              ))}
            </div>
          ) : (
            <div className="card px-5 py-4 text-[13px] text-fg-3">The engine is idle.</div>
          )}
        </section>
        <section>
          <h2 className="eyebrow mb-3">History</h2>
          {!done.length ? (
            <div className="card">
              <EmptyState icon={<ListChecks className="size-5" />} title="No finished jobs yet" />
            </div>
          ) : (
            <div className="card overflow-hidden">
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="border-b border-white/[0.06] text-left text-[11px] text-fg-4">
                    <th className="px-5 py-2.5 font-medium">Job</th>
                    <th className="px-3 py-2.5 font-medium">Production</th>
                    <th className="px-3 py-2.5 font-medium">Status</th>
                    <th className="px-3 py-2.5 font-medium">Shots</th>
                    <th className="px-3 py-2.5 font-medium">Duration</th>
                    <th className="px-5 py-2.5 text-right font-medium">When</th>
                  </tr>
                </thead>
                <tbody>
                  {done.map((j) => (
                    <tr key={j.id} className="border-b border-white/[0.04] last:border-0 hover:bg-white/[0.02]">
                      <td className="px-5 py-3 font-mono text-[11.5px] text-fg-2">{j.id}</td>
                      <td className="px-3">
                        <Link to={`/p/${j.production}?tab=activity`} className="text-fg hover:text-amber">
                          {j.production}
                        </Link>
                      </td>
                      <td className="px-3">
                        <StatusPill status={j.status} />
                      </td>
                      <td className="px-3 font-mono text-[11.5px] text-fg-3">{j.summary ? `${j.summary.shots_done}/${j.summary.shots_total}` : "—"}</td>
                      <td className="px-3 text-fg-3">{j.started && j.ended ? duration(j.ended - j.started) : "—"}</td>
                      <td className="px-5 text-right text-fg-4">{ago(j.created)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </>
  );
}

function ActiveJob({ job, onCancel }: { job: Job; onCancel: () => void }) {
  const detail = useQuery({ queryKey: ["job", job.id], queryFn: () => api.job(job.id), refetchInterval: 3000 });
  const p = detail.data?.progress;
  return (
    <div className="card flex flex-wrap items-center gap-5 border-amber/20 p-5">
      <div className="min-w-[260px] flex-1">
        <div className="flex items-center gap-2.5">
          <StatusPill status={job.status} />
          <Link to={`/p/${job.production}?tab=pipeline`} className="text-[14px] font-medium text-fg hover:text-amber">
            {job.production}
          </Link>
          <span className="font-mono text-[11px] text-fg-4">{job.id}</span>
        </div>
        <div className="mt-2 text-[12px] text-fg-3">
          {job.status === "queued"
            ? "Waiting for the engine"
            : p?.current_shot
              ? `Shot ${p.current_shot} · take ${(p.current_take ?? 0) + 1} · ${p.renders_done} renders so far`
              : (p?.phase ?? "starting")}
          {job.started && ` · started ${stamp(job.started)}`}
          {p?.eta_s && ` · ≈ ${duration(p.eta_s)} left`}
        </div>
        <ProgressBar value={p ? pct(p.shots_done, p.shots_total) : 0} live={job.status === "running"} className="mt-3 max-w-xl" />
      </div>
      <Button variant="danger" size="sm" icon={<Square className="size-3 fill-current" />} onClick={onCancel}>
        {job.status === "queued" ? "Remove" : "Cancel"}
      </Button>
    </div>
  );
}
