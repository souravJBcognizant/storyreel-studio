import { ListTree, Mic2, Package } from "lucide-react";
import { EmptyState, SectionTitle } from "../../components/ui";
import { thumbUrl, type Production } from "../../lib/api";
import { clock } from "../../lib/format";

export function PlanTab({ p }: { p: Production }) {
  if (!p.scenes.length)
    return (
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="card">
          <EmptyState icon={<ListTree className="size-5" />} title="No plan yet">
            The Screenwriter and ShotPlanner agents draft the plan from your story and first frame. You review and approve it here
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
              {scene.shots.map((shot) => (
                <li key={shot.id} className="grid grid-cols-[56px_minmax(0,1fr)_auto] gap-4 border-b border-white/[0.04] px-5 py-3.5 last:border-0">
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
                  <div className="text-right font-mono text-[10.5px] text-fg-4">
                    {shot.seconds ? `${shot.seconds}s` : "auto"}
                    {shot.from && <div className="mt-1">← {shot.from}</div>}
                  </div>
                </li>
              ))}
            </ol>
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
