import { useQuery } from "@tanstack/react-query";
import { Clapperboard, Film, Play, Plus } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { PageHeader } from "../components/AppShell";
import { Button, EmptyState, ProgressBar, StatusPill } from "../components/ui";
import { api, thumbUrl, type ProductionSummary } from "../lib/api";
import { ago, clock, pct } from "../lib/format";

export function productionState(p: ProductionSummary) {
  if (p.active_job?.status === "queued") return { status: "queued" as const, label: "Queued" };
  if (p.active_job?.kind === "preprod") return { status: "running" as const, label: "Agents planning" };
  if (p.active_job?.kind === "audition") return { status: "running" as const, label: "Voice audition" };
  if (p.active_job) return { status: "running" as const, label: p.progress ? `Rendering ${p.progress.shots_done}/${p.progress.shots_total}` : "Rendering" };
  if (p.steps.plan === "awaiting_approval" || p.steps.keyframes === "awaiting_approval" || p.steps.voice === "awaiting_approval")
    return { status: "awaiting_approval" as const, label: "Needs your approval" };
  if (p.steps.film === "done") return { status: "done" as const, label: "Ready to watch" };
  if (p.steps.render === "failed") return { status: "failed" as const, label: "Render failed" };
  if (p.steps.plan !== "done") return { status: "pending" as const, label: "Draft · needs a plan" };
  return { status: "pending" as const, label: "Ready to render" };
}

export function ProductionsPage() {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({ queryKey: ["productions"], queryFn: api.productions, refetchInterval: 4000 });
  return (
    <>
      <PageHeader
        eyebrow="Studio"
        title="Productions"
        subtitle="Every film starts with a first frame and a story. The agents plan it, you approve the key moments, and the render engine on this Mac makes it."
        actions={
          <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => navigate("/new")}>
            New production
          </Button>
        }
      />
      <div className="px-8 py-7">
        {isLoading && (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-5">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton aspect-[16/12]" />
            ))}
          </div>
        )}
        {data && !data.length && (
          <div className="card">
            <EmptyState
              icon={<Clapperboard className="size-5" />}
              title="No productions yet"
              action={
                <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => navigate("/new")}>
                  Start your first film
                </Button>
              }
            >
              Upload an opening frame, write the story, and the studio takes it from there.
            </EmptyState>
          </div>
        )}
        {data && data.length > 0 && (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-5">
            {data.map((p, i) => (
              <ProductionCard key={p.id} p={p} index={i} />
            ))}
            <Link
              to="/new"
              className="group flex min-h-[300px] flex-col items-center justify-center rounded-[var(--radius-card)] border border-dashed border-white/[0.1] text-fg-3 transition-colors hover:border-amber/40 hover:text-fg"
            >
              <span className="flex size-11 items-center justify-center rounded-2xl border border-white/[0.08] bg-ink-850 transition-colors group-hover:border-amber/40 group-hover:text-amber">
                <Plus className="size-5" />
              </span>
              <span className="mt-3 text-[13px] font-medium">New production</span>
              <span className="mt-1 text-[11.5px] text-fg-4">First frame + story</span>
            </Link>
          </div>
        )}
      </div>
    </>
  );
}

function ProductionCard({ p, index }: { p: ProductionSummary; index: number }) {
  const state = productionState(p);
  const poster = p.poster ? thumbUrl(p.poster, 13, 720) : p.first_frame ? thumbUrl(p.first_frame, 0, 720) : null;
  return (
    <Link
      to={`/p/${p.id}`}
      className="group card animate-rise overflow-hidden transition-all hover:-translate-y-0.5 hover:border-white/[0.12]"
      style={{ animationDelay: `${index * 50}ms` }}
    >
      <div className="relative aspect-[16/10] overflow-hidden bg-ink-900">
        {poster ? (
          <img src={poster} alt="" className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-[1.03]" />
        ) : (
          <div className="flex h-full items-center justify-center text-fg-4">
            <Film className="size-8" strokeWidth={1.3} />
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-ink-950 via-ink-950/20 to-transparent" />
        {p.poster && (
          <span className="absolute top-1/2 left-1/2 flex size-12 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-black/40 text-white opacity-0 ring-1 ring-white/25 backdrop-blur-md transition-opacity group-hover:opacity-100">
            <Play className="ml-0.5 size-5 fill-current" />
          </span>
        )}
        <div className="absolute top-3 left-3">
          <StatusPill status={state.status} label={state.label} className="bg-black/50 backdrop-blur-md" />
        </div>
        {p.film_seconds != null && (
          <span className="absolute top-3 right-3 rounded-md bg-black/55 px-1.5 py-0.5 font-mono text-[10.5px] text-white/90 backdrop-blur">
            {clock(p.film_seconds)}
          </span>
        )}
        <div className="absolute inset-x-4 bottom-3">
          <h3 className="font-display text-[21px] leading-tight font-medium text-fg">{p.title}</h3>
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 px-4 py-3 text-[11.5px] text-fg-3">
        <span>
          {p.shots_done ? `${p.shots_done} shots · ${p.takes} takes` : `Target ${clock(p.target_seconds)}`}
        </span>
        <span>{p.source.startsWith("Stage") ? "Imported test" : `Created ${ago(p.created)}`}</span>
      </div>
      {p.progress && p.active_job && (
        <div className="px-4 pb-3.5">
          <ProgressBar value={pct(p.progress.shots_done, p.progress.shots_total)} live />
        </div>
      )}
    </Link>
  );
}
