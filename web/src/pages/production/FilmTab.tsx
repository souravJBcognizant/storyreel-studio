import clsx from "clsx";
import { Download, Film } from "lucide-react";
import { useState } from "react";
import { EmptyState, Stat } from "../../components/ui";
import { VideoPlayer } from "../../components/VideoPlayer";
import { mediaUrl, thumbUrl, type Production } from "../../lib/api";
import { clock, duration } from "../../lib/format";

export function FilmTab({ p, onOpenShot }: { p: Production; onOpenShot: (id: string) => void }) {
  const [seek, setSeek] = useState<{ t: number; n: number }>();
  const [current, setCurrent] = useState<string | null>(null);
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

  return (
    <div className="grid gap-6 2xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0">
        <VideoPlayer
          src={mediaUrl(p.film.path)}
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
            href={mediaUrl(p.film.path)}
            download={`${p.id}.mp4`}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[12px] text-fg-3 hover:bg-white/[0.05] hover:text-fg"
          >
            <Download className="size-3.5" /> Download
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
                  </div>
                </button>
              </li>
            );
          })}
        </ol>
      </aside>
    </div>
  );
}
