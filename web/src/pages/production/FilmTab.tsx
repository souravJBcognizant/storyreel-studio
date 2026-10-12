import clsx from "clsx";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Film, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Button, EmptyState, Stat } from "../../components/ui";
import { VideoPlayer } from "../../components/VideoPlayer";
import { api, mediaUrl, thumbUrl, type Production } from "../../lib/api";
import { clock, duration } from "../../lib/format";

export function FilmTab({ p, onOpenShot }: { p: Production; onOpenShot: (id: string) => void }) {
  const [seek, setSeek] = useState<{ t: number; n: number }>();
  const [current, setCurrent] = useState<string | null>(null);
  const qc = useQueryClient();
  const rebuild = useMutation({
    mutationFn: () => api.rebuildFilm(p.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["production", p.id] });
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  if (!p.film)
    return (
      <div className="card">
        <EmptyState icon={<Film className="size-5" />} title="No film yet">
          The finished film plays here once the render and edit are done.
        </EmptyState>
      </div>
    );

  const shots = p.scenes.flatMap((s) => s.shots.map((shot) => ({ ...shot, scene: s.id })));
  const takes = shots.flatMap((s) => s.takes);
  const rendered = takes.filter((t) => !t.cached);
  const rebuilding = p.active_job?.kind === "export";
  const focusedEdit = p.active_job?.kind === "clip" ? "Generating a new clip…" : p.active_job?.kind === "overlay" ? "Generating new overlay audio…" : null;
  const downloadReady = !p.film.audio_pending && !p.active_job && !rebuild.isPending;
  const filmUrl = `${mediaUrl(p.film.path)}?v=${p.film.revision}`;
  const lastExport = p.jobs.find((j) => j.kind === "export");

  return (
    <div className="grid gap-6 2xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0">
        <div className="card mb-4 flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="min-w-0 flex-1 text-[12px] text-fg-3" aria-live="polite">
            <p className="font-medium text-fg-2">
              {focusedEdit ?? (rebuilding ? "Rebuilding film…" : p.film.audio_pending ? "Audio choices saved · rebuild to apply" : p.film.audio_upgrade ? "Improved overlay sync is available" : "Your shareable MP4 is ready")}
            </p>
            <p className="mt-1">Open a shot to choose original audio or overlay audio. Rebuilding syncs the overlay to the original speech using your existing video takes.</p>
            {p.film.audio_pending && <p className="mt-1 text-amber">The player shows the previous export until the rebuild finishes.</p>}
            {(rebuild.error || (!rebuilding && lastExport?.status === "failed")) && (
              <p role="alert" className="mt-2 text-bad">{rebuild.error?.message ?? lastExport?.error}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" icon={<RefreshCw className="size-3.5" />} loading={rebuild.isPending || rebuilding} disabled={!!p.active_job} onClick={() => rebuild.mutate()}>
              Rebuild film
            </Button>
            <a
              href={downloadReady ? filmUrl : undefined}
              aria-disabled={!downloadReady}
              download={`${p.id}.mp4`}
              className={clsx("inline-flex h-8 items-center gap-2 rounded-lg bg-amber px-3 text-[12.5px] font-medium text-ink-950", !downloadReady && "pointer-events-none opacity-40")}
              title={downloadReady ? "Download one complete, shareable MP4" : "Wait for the current rebuild before exporting"}
            >
              <Download className="size-3.5" /> Export MP4
            </a>
          </div>
        </div>
        <VideoPlayer
          key={filmUrl}
          src={filmUrl}
          poster={thumbUrl(p.film.path, 7.5, 1280)}
          markers={p.film.markers}
          seek={seek}
          onShotChange={setCurrent}
          className="aspect-[3/2] w-full"
        />
        <div className="mt-5 grid grid-cols-2 gap-6 md:grid-cols-5">
          <Stat label="Length" value={clock(p.film.duration)} />
          <Stat label="Shots" value={p.film.markers.length} hint={`${p.scenes.length} scenes`} />
          <Stat label="Takes" value={takes.length} hint={`${takes.filter((t) => !t.passed).length} rejected by QA`} />
          <Stat label="LTX time" value={duration(rendered.reduce((a, t) => a + t.render_s, 0))} />
          <Stat label="Per film-second" value={`${Math.round(rendered.reduce((a, t) => a + t.render_s, 0) / (p.film.duration || 1))} s`} hint="render cost" />
        </div>
        {p.film.report && (
          <details className="card group mt-6 p-4">
            <summary className="cursor-pointer list-none text-[13px] font-medium text-fg-2 select-none hover:text-fg">QA report (report.md)</summary>
            <pre className="mt-3 overflow-x-auto font-mono text-[11px] leading-relaxed text-fg-3">{p.film.report}</pre>
          </details>
        )}
      </div>

      <aside className="card flex max-h-[720px] flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-3">
          <span className="text-[13px] font-medium text-fg">Shot list</span>
          <a
            href={downloadReady ? filmUrl : undefined}
            aria-disabled={!downloadReady}
            title={downloadReady ? "Download the exported film" : "Rebuild the film to apply your audio choices before downloading"}
            download={`${p.id}.mp4`}
            className={clsx("inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[12px] text-fg-3", downloadReady ? "hover:bg-white/[0.05] hover:text-fg" : "cursor-not-allowed opacity-40")}
          >
            <Download className="size-3.5" /> MP4
          </a>
        </div>
        <ol className="flex-1 overflow-y-auto p-2">
          {p.film.markers.map((m) => {
            const shot = shots.find((s) => s.id === m.shot);
            const take = shot && shot.chosen != null ? shot.takes[shot.chosen] : null;
            return (
              <li key={m.shot}>
                <button
                  onClick={() => setSeek({ t: m.start + 0.01, n: Date.now() })}
                  onDoubleClick={() => onOpenShot(m.shot)}
                  className={clsx(
                    "flex w-full items-center gap-3 rounded-lg p-2 text-left transition-colors",
                    current === m.shot ? "bg-amber/[0.08] ring-1 ring-amber/30" : "hover:bg-white/[0.04]",
                  )}
                  title="Click to jump · double-click for the shot's takes"
                >
                  {take && <img src={thumbUrl(take.path, 1.2, 200)} alt="" className="aspect-[3/2] w-[72px] shrink-0 rounded-md object-cover" loading="lazy" />}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 font-mono text-[10.5px] text-fg-3">
                      <span className="text-fg-2">{m.shot}</span> {clock(m.start)} <span className="text-fg-4 capitalize">· {m.scene}</span>
                    </div>
                    <div className="mt-0.5 line-clamp-2 text-[12px] leading-snug text-fg-2">{shot?.line ? `“${shot.line}”` : m.label}</div>
                    {shot?.has_cast_audio && <div className="mt-1 text-[10.5px] text-fg-4">Export: {shot.audio_source === "original" ? "Original audio" : "Overlay audio"}</div>}
                  </div>
                </button>
                <button onClick={() => onOpenShot(m.shot)} className="mb-1 ml-[92px] rounded px-1 py-1 text-[11px] text-amber hover:bg-white/[0.04]" aria-label={`Edit shot and audio for ${m.shot}`}>
                  Edit shot & audio
                </button>
              </li>
            );
          })}
        </ol>
      </aside>
    </div>
  );
}
