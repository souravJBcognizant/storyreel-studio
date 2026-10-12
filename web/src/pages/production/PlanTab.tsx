import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Copy, ListTree, Mic2, Package, Pencil, Plus, Trash2, X } from "lucide-react";
import { cloneElement, useState, type ReactElement } from "react";
import { Button, EmptyState, SectionTitle } from "../../components/ui";
import { api, thumbUrl, type Production, type Scene, type SceneCreateInput, type Shot, type ShotEditInput } from "../../lib/api";
import { clock } from "../../lib/format";

const field = "w-full rounded-lg border border-white/[0.08] bg-ink-850 px-3 py-2 text-[12.5px] text-fg outline-none focus:border-amber/50";
const emptyShot: ShotEditInput = { action: "", camera: "", seconds: 4, line: "", character: null, speaker: null, delivery: "on" };

export function PlanTab({ p, onOpenShot }: { p: Production; onOpenShot: (shot: string) => void }) {
  const qc = useQueryClient();
  const [showSceneForm, setShowSceneForm] = useState(false);
  const [sceneMode, setSceneMode] = useState<SceneCreateInput["mode"]>("blank");
  const [sceneDraft, setSceneDraft] = useState({ name: "", setting: "", audio: "", action: "", camera: "", seconds: 4 });
  const [sourceProduction, setSourceProduction] = useState("");
  const [sourceScene, setSourceScene] = useState("");
  const [reuseTakes, setReuseTakes] = useState(true);
  const [editingScene, setEditingScene] = useState<string | null>(null);
  const [sceneMeta, setSceneMeta] = useState({ setting: "", audio: "" });
  const [editingShot, setEditingShot] = useState<string | null>(null);
  const [addingTo, setAddingTo] = useState<{ scene: string; after: string | null } | null>(null);
  const [shotDraft, setShotDraft] = useState<ShotEditInput>(emptyShot);

  const edited = (next: Production) => {
    qc.setQueryData(["production", p.id], next);
    void qc.invalidateQueries({ queryKey: ["productions"] });
  };
  const reorderShots = useMutation({ mutationFn: ({ scene, ids }: { scene: string; ids: string[] }) => api.reorderShots(p.id, scene, ids), onSuccess: edited });
  const reorderScenes = useMutation({ mutationFn: (ids: string[]) => api.reorderScenes(p.id, ids), onSuccess: edited });
  const removeShot = useMutation({ mutationFn: (shot: string) => api.deleteShot(p.id, shot), onSuccess: edited });
  const removeScene = useMutation({ mutationFn: (scene: string) => api.deleteScene(p.id, scene), onSuccess: edited });
  const createScene = useMutation({ mutationFn: (input: SceneCreateInput) => api.addScene(p.id, input), onSuccess: edited });
  const saveScene = useMutation({ mutationFn: ({ scene, setting, audio }: { scene: string; setting: string; audio: string }) => api.updateScene(p.id, scene, setting, audio), onSuccess: edited });
  const createShot = useMutation({ mutationFn: ({ scene, after, input }: { scene: string; after: string | null; input: ShotEditInput }) => api.addShot(p.id, scene, { ...input, after }), onSuccess: edited });
  const saveShot = useMutation({ mutationFn: ({ shot, input }: { shot: string; input: ShotEditInput }) => api.updateShot(p.id, shot, input), onSuccess: edited });

  const { data: productions = [] } = useQuery({ queryKey: ["productions"], queryFn: api.productions, enabled: showSceneForm && sceneMode === "import" });
  const { data: source } = useQuery({ queryKey: ["production", sourceProduction], queryFn: () => api.production(sourceProduction), enabled: !!sourceProduction && sceneMode === "import" });
  const busy = !!p.active_job;
  const error = [reorderShots, reorderScenes, removeShot, removeScene, createScene, saveScene, createShot, saveShot].find((m) => m.error)?.error;

  const moveShot = (scene: Scene, index: number, offset: number) => {
    const ids = scene.shots.map((shot) => shot.id);
    [ids[index], ids[index + offset]] = [ids[index + offset], ids[index]];
    reorderShots.mutate({ scene: scene.id, ids });
  };
  const moveScene = (index: number, offset: number) => {
    const ids = p.scenes.map((scene) => scene.id);
    [ids[index], ids[index + offset]] = [ids[index + offset], ids[index]];
    reorderScenes.mutate(ids);
  };
  const beginShot = (scene: string, after: string | null, shot?: Shot) => {
    setAddingTo(shot ? null : { scene, after });
    setEditingShot(shot?.id ?? null);
    setShotDraft(shot ? { action: shot.action, camera: shot.camera, seconds: shot.seconds ?? 4, line: shot.line ?? "", character: shot.character, speaker: shot.speaker, delivery: shot.delivery } : { ...emptyShot });
  };
  const submitScene = () => {
    const input: SceneCreateInput = sceneMode === "blank"
      ? { mode: "blank", ...sceneDraft }
      : { mode: sceneMode, source_production: sceneMode === "import" ? sourceProduction : p.id, source_scene: sourceScene, reuse_takes: reuseTakes };
    createScene.mutate(input, { onSuccess: () => { setShowSceneForm(false); setSourceScene(""); } });
  };

  if (!p.scenes.length) return <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]"><div className="card"><EmptyState icon={<ListTree className="size-5" />} title="No plan yet">The Screenwriter and ShotPlanner agents draft the first plan. Once it exists, scenes and shots can be added here.</EmptyState></div><StoryCard p={p} /></div>;

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="flex flex-col gap-6">
        <div className="flex items-center justify-between gap-4"><div><h2 className="text-[15px] font-semibold">Scenes and shots</h2><p className="mt-0.5 text-[12px] text-fg-4">Click a shot to open its references, takes and re-render controls.</p></div><Button size="sm" variant="primary" icon={<Plus className="size-4" />} disabled={busy} onClick={() => setShowSceneForm((v) => !v)}>Add scene</Button></div>

        {showSceneForm && <section className="card p-5">
          <div className="flex items-start justify-between"><SectionTitle eyebrow="Timeline" title="Add a scene" /><button onClick={() => setShowSceneForm(false)} className="p-1 text-fg-4 hover:text-fg"><X className="size-4" /></button></div>
          <div className="mb-4 flex flex-wrap gap-2">{(["blank", "duplicate", "import"] as const).map((mode) => <button key={mode} onClick={() => { setSceneMode(mode); setSourceScene(""); }} className={`rounded-lg border px-3 py-2 text-[12px] ${sceneMode === mode ? "border-amber/40 bg-amber/10 text-amber" : "border-white/[0.08] text-fg-3"}`}>{mode === "blank" ? "Start blank" : mode === "duplicate" ? "Duplicate this production" : "From another production"}</button>)}</div>
          {sceneMode === "blank" ? <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-[11px] text-fg-4">Scene name<input className={`${field} mt-1`} value={sceneDraft.name} onChange={(e) => setSceneDraft({ ...sceneDraft, name: e.target.value })} placeholder="Rooftop at dawn" /></label>
            <label className="text-[11px] text-fg-4">Setting<input className={`${field} mt-1`} value={sceneDraft.setting} onChange={(e) => setSceneDraft({ ...sceneDraft, setting: e.target.value })} placeholder="A rain-wet rooftop above the city" /></label>
            <label className="text-[11px] text-fg-4">Sound<input className={`${field} mt-1`} value={sceneDraft.audio} onChange={(e) => setSceneDraft({ ...sceneDraft, audio: e.target.value })} placeholder="Distant traffic and soft wind" /></label>
            <label className="text-[11px] text-fg-4">First shot duration<input type="number" min={1} max={30} step={0.5} className={`${field} mt-1`} value={sceneDraft.seconds} onChange={(e) => setSceneDraft({ ...sceneDraft, seconds: Number(e.target.value) })} /></label>
            <label className="text-[11px] text-fg-4 sm:col-span-2">What happens first?<textarea rows={2} className={`${field} mt-1`} value={sceneDraft.action} onChange={(e) => setSceneDraft({ ...sceneDraft, action: e.target.value })} placeholder="The camera finds..." /></label>
            <label className="text-[11px] text-fg-4 sm:col-span-2">Camera (optional)<input className={`${field} mt-1`} value={sceneDraft.camera} onChange={(e) => setSceneDraft({ ...sceneDraft, camera: e.target.value })} placeholder="Slow push in" /></label>
          </div> : <div className="grid gap-3 sm:grid-cols-2">
            {sceneMode === "import" && <label className="text-[11px] text-fg-4">Production<select className={`${field} mt-1`} value={sourceProduction} onChange={(e) => { setSourceProduction(e.target.value); setSourceScene(""); }}><option value="">Choose a production</option>{productions.filter((item) => item.id !== p.id).map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>}
            <label className="text-[11px] text-fg-4">Scene<select className={`${field} mt-1`} value={sourceScene} onChange={(e) => setSourceScene(e.target.value)}><option value="">Choose a scene</option>{(sceneMode === "duplicate" ? p.scenes : source?.scenes ?? []).map((scene) => <option key={scene.id} value={scene.id}>{scene.id} — {scene.setting}</option>)}</select></label>
            <label className="flex items-center gap-2 self-end pb-2 text-[12px] text-fg-3"><input type="checkbox" checked={reuseTakes} onChange={(e) => setReuseTakes(e.target.checked)} className="accent-amber" />Copy finished takes when available</label>
          </div>}
          <div className="mt-4 flex justify-end gap-2"><Button size="sm" variant="ghost" onClick={() => setShowSceneForm(false)}>Cancel</Button><Button size="sm" variant="primary" loading={createScene.isPending} disabled={sceneMode !== "blank" && !sourceScene} onClick={submitScene}>Add scene</Button></div>
        </section>}

        {p.scenes.map((scene, si) => <section key={scene.id} className="card overflow-hidden">
          <div className="flex items-start justify-between gap-4 border-b border-white/[0.06] bg-white/[0.015] px-5 py-3.5">
            {editingScene === scene.id ? <div className="grid flex-1 gap-2 sm:grid-cols-2"><input className={field} value={sceneMeta.setting} onChange={(e) => setSceneMeta({ ...sceneMeta, setting: e.target.value })} aria-label="Scene setting" /><input className={field} value={sceneMeta.audio} onChange={(e) => setSceneMeta({ ...sceneMeta, audio: e.target.value })} aria-label="Scene sound" /><div className="flex gap-2 sm:col-span-2"><Button size="sm" variant="primary" loading={saveScene.isPending} onClick={() => saveScene.mutate({ scene: scene.id, ...sceneMeta }, { onSuccess: () => setEditingScene(null) })}>Save scene</Button><Button size="sm" variant="ghost" onClick={() => setEditingScene(null)}>Cancel</Button></div></div> : <div><div className="font-mono text-[10.5px] tracking-[0.12em] text-fg-4">SCENE {si + 1} — {scene.id.toUpperCase()}</div><div className="mt-1 text-[13px] text-fg-2">{scene.setting}</div><div className="mt-0.5 text-[11.5px] text-fg-4">Sound: {scene.audio}</div></div>}
            {editingScene !== scene.id && <div className="flex rounded-md border border-white/[0.06] bg-ink-900">
              <Icon title="Move scene earlier" disabled={busy || si === 0} onClick={() => moveScene(si, -1)}><ArrowUp /></Icon><Icon title="Move scene later" disabled={busy || si === p.scenes.length - 1} onClick={() => moveScene(si, 1)}><ArrowDown /></Icon><Icon title="Edit scene" disabled={busy} onClick={() => { setEditingScene(scene.id); setSceneMeta({ setting: scene.setting, audio: scene.audio }); }}><Pencil /></Icon><Icon title="Duplicate scene" disabled={busy} onClick={() => createScene.mutate({ mode: "duplicate", source_production: p.id, source_scene: scene.id, reuse_takes: true })}><Copy /></Icon><Icon title="Delete scene" disabled={busy || p.scenes.length === 1} danger onClick={() => window.confirm(`Delete scene ${scene.id} and its shots?`) && removeScene.mutate(scene.id)}><Trash2 /></Icon>
            </div>}
          </div>
          <ol>{scene.shots.map((shot, shotIndex) => <li key={shot.id} className="border-b border-white/[0.04] last:border-0">
            {editingShot === shot.id ? <ShotForm draft={shotDraft} setDraft={setShotDraft} characters={p.characters} submitLabel="Save shot" pending={saveShot.isPending} onCancel={() => setEditingShot(null)} onSubmit={() => saveShot.mutate({ shot: shot.id, input: shotDraft }, { onSuccess: () => setEditingShot(null) })} /> : <div onClick={() => onOpenShot(shot.id)} className="group grid cursor-pointer grid-cols-[56px_minmax(0,1fr)_auto] gap-4 px-5 py-3.5 transition-colors hover:bg-white/[0.025]">
              <div className="font-mono text-[11px] text-fg-3">{shot.id}<div className="mt-1 text-[10px] text-fg-4">{shot.start}</div></div>
              <div className="min-w-0 text-[13px] leading-relaxed"><p className="text-fg-2">{shot.action}</p>{shot.line && <p className="mt-1.5 flex gap-2 text-fg"><Mic2 className="mt-1 size-3.5 shrink-0 text-engine-claude" /><span><span className="font-mono text-[10.5px] tracking-wider text-fg-4 uppercase">{shot.speaker} </span>“{shot.line}”</span></p>}{shot.camera && <p className="mt-1 text-[12px] text-fg-4 italic">{shot.camera}</p>}</div>
              <div className="flex min-w-[126px] flex-col items-end text-right font-mono text-[10.5px] text-fg-4"><span>{shot.seconds ? `${shot.seconds}s` : "auto"}</span>{shot.from && <span className="mt-1">← {shot.from}</span>}<div className="mt-2 flex rounded-md border border-white/[0.06] bg-ink-900 opacity-40 transition-opacity group-hover:opacity-100 focus-within:opacity-100" onClick={(e) => e.stopPropagation()}><Icon title="Move earlier" disabled={busy || shotIndex === 0} compact onClick={() => moveShot(scene, shotIndex, -1)}><ArrowUp /></Icon><Icon title="Move later" disabled={busy || shotIndex === scene.shots.length - 1} compact onClick={() => moveShot(scene, shotIndex, 1)}><ArrowDown /></Icon><Icon title="Edit shot details" disabled={busy} compact onClick={() => beginShot(scene.id, shot.id, shot)}><Pencil /></Icon><Icon title="Add shot after" disabled={busy} compact onClick={() => beginShot(scene.id, shot.id)}><Plus /></Icon><Icon title="Remove shot" disabled={busy} danger compact onClick={() => window.confirm(`Remove shot ${shot.id}?`) && removeShot.mutate(shot.id)}><Trash2 /></Icon></div></div>
            </div>}
            {addingTo?.scene === scene.id && addingTo.after === shot.id && <ShotForm draft={shotDraft} setDraft={setShotDraft} characters={p.characters} submitLabel="Add shot here" pending={createShot.isPending} onCancel={() => setAddingTo(null)} onSubmit={() => createShot.mutate({ scene: scene.id, after: shot.id, input: shotDraft }, { onSuccess: () => setAddingTo(null) })} />}
          </li>)}</ol>
          <div className="border-t border-white/[0.04] p-3"><Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} disabled={busy} onClick={() => beginShot(scene.id, scene.shots.at(-1)?.id ?? null)}>Add shot to scene</Button></div>
        </section>)}
        {error && <p role="alert" className="text-[12px] text-bad">{error.message}</p>}
      </div>

      <aside className="flex flex-col gap-5">
        {p.characters.map((c) => <section key={c.id} className="card overflow-hidden">{c.image && <img src={thumbUrl(c.image, 0, 720)} alt="" className="aspect-[3/2] w-full object-cover" />}<div className="p-4"><div className="eyebrow">Character · {c.id}</div><p className="mt-2 text-[12.5px] leading-relaxed text-fg-2">{c.bible}</p><div className="mt-3 rounded-lg border border-white/[0.06] bg-ink-900/70 px-3 py-2 text-[12px] text-fg-2"><span className="text-fg-4">Voice · </span>“{c.voice_phrase}”<div className="mt-0.5 text-[11px] text-fg-4">{c.voice_refs} approved takes form the QA reference</div></div></div></section>)}
        {Object.keys(p.props).length > 0 && <section className="card p-4"><SectionTitle eyebrow="Props" title="Locked descriptions" />{Object.entries(p.props).map(([k, v]) => <div key={k} className="flex gap-2.5 text-[12.5px] leading-relaxed text-fg-2"><Package className="mt-1 size-3.5 shrink-0 text-fg-3" /><span><span className="font-mono text-[11px] text-fg-3">{k}</span> — {v}</span></div>)}</section>}
        <StoryCard p={p} />
      </aside>
    </div>
  );
}

function Icon({ title, disabled, danger, compact, onClick, children }: { title: string; disabled?: boolean; danger?: boolean; compact?: boolean; onClick: () => void; children: ReactElement<{ className?: string }> }) {
  return <button type="button" title={title} aria-label={title} disabled={disabled} onClick={onClick} className={`${compact ? "p-1.5" : "p-2"} text-fg-4 ${danger ? "hover:text-bad" : "hover:text-fg"} disabled:opacity-25`}>{cloneElement(children, { className: compact ? "size-3" : "size-3.5" })}</button>;
}

function ShotForm({ draft, setDraft, characters, submitLabel, pending, onCancel, onSubmit }: { draft: ShotEditInput; setDraft: (value: ShotEditInput) => void; characters: Production["characters"]; submitLabel: string; pending: boolean; onCancel: () => void; onSubmit: () => void }) {
  return <div className="bg-ink-900/50 px-5 py-4"><div className="grid gap-3 sm:grid-cols-2"><label className="text-[11px] text-fg-4 sm:col-span-2">Action<textarea rows={2} className={`${field} mt-1`} value={draft.action} onChange={(e) => setDraft({ ...draft, action: e.target.value })} /></label><label className="text-[11px] text-fg-4">Camera<input className={`${field} mt-1`} value={draft.camera} onChange={(e) => setDraft({ ...draft, camera: e.target.value })} /></label><label className="text-[11px] text-fg-4">Duration<input type="number" min={1} max={30} step={0.5} className={`${field} mt-1`} value={draft.seconds} onChange={(e) => setDraft({ ...draft, seconds: Number(e.target.value) })} /></label><label className="text-[11px] text-fg-4">Character in frame<select className={`${field} mt-1`} value={draft.character ?? ""} onChange={(e) => setDraft({ ...draft, character: e.target.value || null, speaker: draft.speaker ?? (e.target.value || null) })}><option value="">No specific character</option>{characters.map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}</select></label><label className="text-[11px] text-fg-4">Line (optional)<input className={`${field} mt-1`} value={draft.line} onChange={(e) => setDraft({ ...draft, line: e.target.value })} /></label>{draft.line && <><label className="text-[11px] text-fg-4">Speaker<select className={`${field} mt-1`} value={draft.speaker ?? ""} onChange={(e) => setDraft({ ...draft, speaker: e.target.value || null })}><option value="">Choose</option>{characters.map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}</select></label><label className="text-[11px] text-fg-4">Delivery<select className={`${field} mt-1`} value={draft.delivery} onChange={(e) => setDraft({ ...draft, delivery: e.target.value as "on" | "off" })}><option value="on">On camera</option><option value="off">Off camera / voice-over</option></select></label></>}</div><div className="mt-3 flex gap-2"><Button size="sm" variant="primary" loading={pending} disabled={!draft.action.trim()} onClick={onSubmit}>{submitLabel}</Button><Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button></div></div>;
}

function StoryCard({ p }: { p: Production }) { return <section className="card p-4"><SectionTitle eyebrow="Story" title={`Target ${clock(p.target_seconds)}`} /><p className="text-[12.5px] leading-relaxed whitespace-pre-wrap text-fg-2">{p.story}</p></section>; }
