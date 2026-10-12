import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ListTree, Mic2, Package, Trash2 } from "lucide-react";
import { EmptyState, SectionTitle } from "../../components/ui";
import { api, thumbUrl, type Production, type Scene, type Shot } from "../../lib/api";
import { clock } from "../../lib/format";

export function PlanTab({ p }: { p: Production }) {
  const qc = useQueryClient();
  const edited = (next: Production) => qc.setQueryData(["production", p.id], next);
  const reorder = useMutation({
    mutationFn: ({ scene, ids }: { scene: string; ids: string[] }) => api.reorderShots(p.id, scene, ids),
    onSuccess: edited,
  });
  const remove = useMutation({ mutationFn: (shot: string) => api.deleteShot(p.id, shot), onSuccess: edited });
  const move = (scene: Scene, index: number, offset: number) => {
    const ids = scene.shots.map((shot) => shot.id);
    const other = index + offset;
    [ids[index], ids[other]] = [ids[other], ids[index]];
    reorder.mutate({ scene: scene.id, ids });
  };
  const removeShot = (shot: Shot) => {
    if (window.confirm(`Remove shot ${shot.id} from the film timeline? Existing rendered files stay in the cache.`)) remove.mutate(shot.id);
  };
  if (!p.scenes.length)
    return (
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="card">
          <EmptyState icon={<ListTree className="size-5" />} title="No plan yet">
            The Screenwriter and ShotPlanner agents draft the plan from your story and reference frames. You review and approve it here
            before anything is rendered.
          </EmptyState>
        </div>
        <StoryCard p={p} />
      </div>
    );
  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="flex flex-col gap-6">
        {p.scenes.map((scene, si) => (
          <section key={scene.id} className="card overflow-hidden">
            <div className="border-b border-white/[0.06] bg-white/[0.015] px-5 py-3.5">
              <div className="font-mono text-[10.5px] tracking-[0.12em] text-fg-4">
                SCENE {si + 1} — {scene.id.toUpperCase()}
              </div>
              <div className="mt-1 text-[13px] text-fg-2">{scene.setting}</div>
              <div className="mt-0.5 text-[11.5px] text-fg-4">Sound: {scene.audio}</div>
            </div>
            <ol>
              {scene.shots.map((shot, shotIndex) => (
                <li key={shot.id} className="group grid grid-cols-[56px_minmax(0,1fr)_auto] gap-4 border-b border-white/[0.04] px-5 py-3.5 last:border-0">
                  <div className="font-mono text-[11px] text-fg-3">
                    {shot.id}
                    <div className="mt-1 text-[10px] text-fg-4">{shot.start}</div>
                  </div>
                  <div className="min-w-0 text-[13px] leading-relaxed">
                    <p className="text-fg-2">{shot.action}</p>
                    {shot.line && (
                      <p className="mt-1.5 flex gap-2 text-fg">
                        <Mic2 className="mt-1 size-3.5 shrink-0 text-engine-claude" />
                        <span>
                          <span className="font-mono text-[10.5px] tracking-wider text-fg-4 uppercase">{shot.character} </span>“{shot.line}”
                        </span>
                      </p>
                    )}
                    {shot.camera && <p className="mt-1 text-[12px] text-fg-4 italic">{shot.camera}</p>}
                  </div>
                  <div className="flex min-w-[82px] flex-col items-end text-right font-mono text-[10.5px] text-fg-4">
                    <span>{shot.seconds ? `${shot.seconds}s` : "auto"}</span>
                    {shot.from && <span className="mt-1">← {shot.from}</span>}
                    <div className="mt-2 flex items-center rounded-md border border-white/[0.06] bg-ink-900 opacity-40 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                      <button type="button" title="Move earlier" aria-label={`Move ${shot.id} earlier`} disabled={!!p.active_job || reorder.isPending || shotIndex === 0} onClick={() => move(scene, shotIndex, -1)} className="p-1.5 hover:text-fg disabled:opacity-25"><ArrowUp className="size-3" /></button>
                      <button type="button" title="Move later" aria-label={`Move ${shot.id} later`} disabled={!!p.active_job || reorder.isPending || shotIndex === scene.shots.length - 1} onClick={() => move(scene, shotIndex, 1)} className="p-1.5 hover:text-fg disabled:opacity-25"><ArrowDown className="size-3" /></button>
                      <button type="button" title="Remove from timeline" aria-label={`Remove ${shot.id}`} disabled={!!p.active_job || remove.isPending} onClick={() => removeShot(shot)} className="p-1.5 hover:bg-bad/10 hover:text-bad disabled:opacity-25"><Trash2 className="size-3" /></button>
                    </div>
                  </div>
                </li>
              ))}
            </ol>
            {(reorder.error || remove.error) && <p role="alert" className="border-t border-white/[0.06] px-5 py-2 text-[11.5px] text-bad">{(reorder.error || remove.error)?.message}</p>}
          </section>
        ))}
      </div>

      <aside className="flex flex-col gap-5">
        {p.characters.map((c) => (
          <section key={c.id} className="card overflow-hidden">
            {c.image && <img src={thumbUrl(c.image, 0, 720)} alt="" className="aspect-[3/2] w-full object-cover" />}
            <div className="p-4">
              <div className="eyebrow">Character · {c.id}</div>
              <p className="mt-2 text-[12.5px] leading-relaxed text-fg-2">{c.bible}</p>
              <div className="mt-3 rounded-lg border border-white/[0.06] bg-ink-900/70 px-3 py-2 text-[12px] text-fg-2">
                <span className="text-fg-4">Voice · </span>“{c.voice_phrase}”
                <div className="mt-0.5 text-[11px] text-fg-4">{c.voice_refs} approved takes form the QA reference</div>
              </div>
            </div>
          </section>
        ))}
        {Object.keys(p.props).length > 0 && (
          <section className="card p-4">
            <SectionTitle eyebrow="Props" title="Locked descriptions" />
            {Object.entries(p.props).map(([k, v]) => (
              <div key={k} className="flex gap-2.5 text-[12.5px] leading-relaxed text-fg-2">
                <Package className="mt-1 size-3.5 shrink-0 text-fg-3" />
                <span>
                  <span className="font-mono text-[11px] text-fg-3">{k}</span> — {v}
                </span>
              </div>
            ))}
          </section>
        )}
        <StoryCard p={p} />
      </aside>
    </div>
  );
}

function StoryCard({ p }: { p: Production }) {
  return (
    <section className="card p-4">
      <SectionTitle eyebrow="Story" title={`Target ${clock(p.target_seconds)}`} />
      <p className="text-[12.5px] leading-relaxed whitespace-pre-wrap text-fg-2">{p.story}</p>
    </section>
  );
}
