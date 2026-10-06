import clsx from "clsx";
import { Anchor, Clapperboard, Link2, Mic2, Sparkles } from "lucide-react";
import { EmptyState, ScoreChip, StatusPill } from "../../components/ui";
import { thumbUrl, type Production } from "../../lib/api";

const START = {
  fresh: { icon: Sparkles, label: "New shot" },
  continue: { icon: Link2, label: "Continues" },
  anchor: { icon: Anchor, label: "Anchored" },
} as const;

export function ShotsTab({ p, onOpenShot }: { p: Production; onOpenShot: (id: string) => void }) {
  if (!p.scenes.length)
    return (
      <div className="card">
        <EmptyState icon={<Clapperboard className="size-5" />} title="No shots yet">
          Shots appear once the plan is drafted and approved.
        </EmptyState>
      </div>
    );
  let n = 0;
  return (
    <div className="flex flex-col gap-8">
      {p.scenes.map((scene, si) => (
        <section key={scene.id}>
          <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="font-mono text-[10.5px] text-fg-4">SCENE {si + 1}</span>
            <h3 className="font-display text-[19px] text-fg capitalize">{scene.id}</h3>
            <span className="text-[12px] text-fg-3">{scene.setting}</span>
            <span className="text-[11.5px] text-fg-4">· sound: {scene.audio}</span>
          </div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-4">
            {scene.shots.map((shot) => {
              n += 1;
              const take = shot.chosen != null ? shot.takes[shot.chosen] : shot.takes[shot.takes.length - 1];
              const Start = START[shot.start];
              return (
                <button
                  key={shot.id}
                  onClick={() => onOpenShot(shot.id)}
                  className={clsx(
                    "group card flex flex-col justify-start overflow-hidden text-left transition-all hover:-translate-y-0.5 hover:border-white/[0.14]",
                    shot.status === "rendering" && "border-amber/40",
                  )}
                >
                  <div className="relative aspect-[3/2] overflow-hidden bg-ink-900">
                    {take ? (
                      <img src={thumbUrl(take.path, 1.2, 520)} alt="" loading="lazy" className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]" />
                    ) : (
                      <div className={clsx("h-full w-full", shot.status === "rendering" && "skeleton rounded-none")} />
                    )}
                    <span className="absolute top-2 left-2 rounded-md bg-black/60 px-1.5 py-0.5 font-mono text-[10.5px] text-white/90 backdrop-blur">
                      {String(n).padStart(2, "0")} · {shot.id}
                    </span>
                    <span className="absolute top-2 right-2 inline-flex items-center gap-1 rounded-md bg-black/60 px-1.5 py-0.5 text-[10px] text-white/80 backdrop-blur">
                      <Start.icon className="size-3" /> {Start.label}
                      {shot.from && <span className="font-mono text-white/60">← {shot.from}</span>}
                    </span>
                  </div>
                  <div className="flex flex-col gap-2 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <StatusPill status={shot.status} />
                      <span className="font-mono text-[10.5px] text-fg-4">
                        {shot.takes.length} take{shot.takes.length === 1 ? "" : "s"}
                        {take && ` · ${take.seconds.toFixed(1)} s`}
                      </span>
                    </div>
                    <p className="line-clamp-2 min-h-[34px] text-[12px] leading-snug text-fg-2">
                      {shot.line ? (
                        <span className="flex gap-1.5">
                          <Mic2 className="mt-0.5 size-3 shrink-0 text-fg-3" />
                          <span className="italic">“{shot.line}”</span>
                        </span>
                      ) : (
                        shot.action
                      )}
                    </p>
                    {shot.chosen != null && take && (
                      <div className="flex flex-wrap gap-1">
                        <ScoreChip metric="words" value={take.wer} />
                        <ScoreChip metric="voice" value={take.voice} />
                        {shot.identity_check && <ScoreChip metric="identity" value={take.identity} />}
                        <ScoreChip metric="continuity" value={take.continuity} />
                      </div>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
