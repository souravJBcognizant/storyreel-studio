import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Bot, Clapperboard, FolderOpen, GitBranch, ListTree, Play, ScrollText, Square, Workflow } from "lucide-react";
import { useCallback, useMemo } from "react";
import { useParams, useSearchParams } from "react-router";
import { PageHeader } from "../../components/AppShell";
import { FileBrowser } from "../../components/FileBrowser";
import { ShotDrawer } from "../../components/ShotDrawer";
import { Button, EmptyState, StatusPill } from "../../components/ui";
import { api, thumbUrl } from "../../lib/api";
import { ago, clock } from "../../lib/format";
import { productionState } from "../ProductionsPage";
import { ActivityTab } from "./ActivityTab";
import { AgentsTab } from "./AgentsTab";
import { FilmTab } from "./FilmTab";
import { PipelineTab } from "./PipelineTab";
import { PlanTab } from "./PlanTab";
import { ShotsTab } from "./ShotsTab";

const TABS = [
  { key: "pipeline", label: "Pipeline", icon: Workflow },
  { key: "agents", label: "Agents", icon: Bot },
  { key: "film", label: "Film", icon: Play },
  { key: "shots", label: "Shots", icon: Clapperboard },
  { key: "plan", label: "Plan", icon: ListTree },
  { key: "activity", label: "Activity", icon: ScrollText },
  { key: "files", label: "Files", icon: FolderOpen },
] as const;
type TabKey = (typeof TABS)[number]["key"];

export function ProductionPage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const tab = (params.get("tab") as TabKey) || "pipeline";
  const shotId = params.get("shot");

  const { data: p, error } = useQuery({
    queryKey: ["production", id],
    queryFn: () => api.production(id),
    refetchInterval: (q) => (q.state.data?.active_job ? 2500 : 15000),
  });

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["production", id] });
    void qc.invalidateQueries({ queryKey: ["jobs"] });
  };
  const render = useMutation({ mutationFn: () => api.startRender(id), onSuccess: refresh });
  const cancel = useMutation({ mutationFn: () => api.cancelJob(p!.active_job!.id), onSuccess: refresh });

  const setTab = (t: TabKey) => setParams((prev) => (prev.set("tab", t), prev.delete("shot"), prev));
  const openShot = useCallback((s: string) => setParams((prev) => (prev.set("shot", s), prev)), [setParams]);
  const closeShot = () => setParams((prev) => (prev.delete("shot"), prev));

  const found = useMemo(() => {
    for (const scene of p?.scenes ?? []) {
      const shot = scene.shots.find((s) => s.id === shotId);
      if (shot) return { scene, shot };
    }
    return { scene: null, shot: null };
  }, [p, shotId]);

  if (error) return <EmptyState icon={<Clapperboard className="size-5" />} title="Production not found" className="mt-24">{String(error)}</EmptyState>;
  if (!p)
    return (
      <div className="px-8 pt-10">
        <div className="skeleton h-10 w-80" />
        <div className="skeleton mt-6 h-[420px] w-full" />
      </div>
    );

  const state = productionState(p);
  const filesRoot = p.out ?? `productions/${p.id}`;

  return (
    <>
      <PageHeader
        eyebrow={
          <span className="flex items-center gap-2">
            <span>Production</span>
            <span className="text-fg-4">·</span>
            <span className="normal-case tracking-normal">{p.source.startsWith("Stage") ? p.source : `created ${ago(p.created)}`}</span>
          </span>
        }
        title={
          <span className="flex items-center gap-4">
            {p.first_frame && <img src={thumbUrl(p.first_frame, 0, 200)} alt="" className="h-11 w-[66px] rounded-lg object-cover ring-1 ring-white/10" />}
            {p.title}
          </span>
        }
        actions={
          <>
            <StatusPill status={state.status} label={state.label} />
            {p.active_job ? (
              <Button variant="danger" icon={<Square className="size-3.5 fill-current" />} loading={cancel.isPending} onClick={() => cancel.mutate()}>
                {p.active_job.status === "queued" ? "Remove from queue" : p.active_job.kind === "render" ? "Cancel render" : "Stop agents"}
              </Button>
            ) : p.scenes.length === 0 ? null : (
              <Button
                variant={p.film ? "secondary" : "primary"}
                icon={<GitBranch className="size-4" />}
                disabled={!p.can_render}
                loading={render.isPending}
                onClick={() => render.mutate()}
                title={p.can_render ? "Renders only what changed; finished takes come from the cache" : "Approve the plan, keyframes and voice first"}
              >
                {p.film ? "Re-render" : "Render film"}
              </Button>
            )}
            {p.film && (
              <Button variant="primary" icon={<Play className="size-4 fill-current" />} onClick={() => setTab("film")}>
                Watch {p.film.duration ? clock(p.film.duration) : ""}
              </Button>
            )}
          </>
        }
      >
        {render.error && <p className="mt-3 text-[12.5px] text-bad">{render.error.message}</p>}
        <nav className="mt-6 -mb-6 flex gap-1" role="tablist">
          {TABS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={clsx(
                "relative flex h-10 items-center gap-2 px-3.5 text-[13px] transition-colors",
                tab === key ? "font-medium text-fg" : "text-fg-3 hover:text-fg",
              )}
            >
              <Icon className={clsx("size-4", tab === key ? "text-amber" : "text-fg-4")} strokeWidth={1.8} />
              {label}
              {key === "activity" && p.active_job && <span className="size-1.5 animate-pulse-soft rounded-full bg-amber" />}
              {key === "agents" && p.active_job?.kind === "preprod" && <span className="size-1.5 animate-pulse-soft rounded-full bg-amber" />}
              {tab === key && <span className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-amber" />}
            </button>
          ))}
        </nav>
      </PageHeader>

      <div className="px-8 py-7">
        {tab === "pipeline" && <PipelineTab p={p} onOpenShot={openShot} onRender={() => render.mutate()} />}
        {tab === "agents" && <AgentsTab p={p} />}
        {tab === "film" && <FilmTab p={p} onOpenShot={openShot} />}
        {tab === "shots" && <ShotsTab p={p} onOpenShot={openShot} />}
        {tab === "plan" && <PlanTab p={p} />}
        {tab === "activity" && <ActivityTab p={p} onCancel={() => cancel.mutate()} />}
        {tab === "files" && <FileBrowser root={filesRoot} />}
      </div>

      <ShotDrawer shot={found.shot} scene={found.scene} onClose={closeShot} />
    </>
  );
}
