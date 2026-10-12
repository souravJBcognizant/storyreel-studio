import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, Check, Copy, Film, Flag, HardDrive, ImagePlus, RefreshCw, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router";
import { PageHeader } from "../components/AppShell";
import { Button, EngineTag } from "../components/ui";
import { api, thumbUrl, type Engine, type ProductionSummary } from "../lib/api";

const LENGTHS = [
  { s: 30, label: "30 s" },
  { s: 60, label: "1 min" },
  { s: 120, label: "2 min" },
  { s: 300, label: "5 min" },
];
const MAX_GUIDES = 6;
type PickedFrame = { file: File; preview: string };

export function NewProductionPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [guides, setGuides] = useState<PickedFrame[]>([]);
  const [ending, setEnding] = useState<PickedFrame | null>(null);
  const previewUrls = useRef(new Set<string>());
  const [storyMode, setStoryMode] = useState<"manual" | "ai">("manual");
  const [title, setTitle] = useState("");
  const [story, setStory] = useState("");
  const [storyPrompt, setStoryPrompt] = useState("Generate an interesting story.");
  const [seconds, setSeconds] = useState(60);
  const [dragging, setDragging] = useState(false);
  const [startMode, setStartMode] = useState<"scratch" | "existing">("scratch");
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  // Nested optional checks keep this page usable while Vite and the API reload at different times.
  const planningEngine: Engine = settings?.providers.language?.provider === "ollama" ? "ollama" : "claude";
  const visionEngine: Engine = settings?.providers.vision?.provider === "ollama" ? "ollama" : "claude";
  const imageEngine: Engine = settings?.providers.images?.provider === "local" ? "local" : "openai";
  const modelCanInspect = !!settings?.providers.vision?.configured;
  const planningSteps: { label: string; engine: Engine; checkpoint?: boolean }[] = settings?.mode === "local"
    ? [
        { label: "Story analysis from text", engine: planningEngine },
        { label: "Screenplay & text-driven shot plan", engine: planningEngine, checkpoint: true },
        { label: "Voice casting", engine: "qwen", checkpoint: true },
        { label: "Render without visual QA, then edit", engine: "ltx" },
      ]
    : [
        { label: "Story analysis", engine: planningEngine },
        { label: "Screenplay & shot plan", engine: planningEngine, checkpoint: true },
        { label: "Voice casting", engine: "qwen", checkpoint: true },
        { label: "Character & prop sheets", engine: imageEngine },
        { label: "Coverage keyframes", engine: imageEngine, checkpoint: true },
        { label: "Render & QA, then the edit", engine: "ltx" },
      ];
  const next = storyMode === "ai"
    ? [{ label: modelCanInspect ? "Invent title & story from the references" : "Invent title & story from your direction", engine: modelCanInspect ? visionEngine : planningEngine }, ...planningSteps]
    : planningSteps;

  useEffect(() => () => previewUrls.current.forEach((url) => URL.revokeObjectURL(url)), []);

  const makePreview = useCallback((f: File): PickedFrame => {
    const url = URL.createObjectURL(f);
    previewUrls.current.add(url);
    return { file: f, preview: url };
  }, []);

  const discardPreview = (picked: PickedFrame) => {
    URL.revokeObjectURL(picked.preview);
    previewUrls.current.delete(picked.preview);
  };

  const pick = useCallback((f: File | undefined) => {
    if (!f || !f.type.startsWith("image/")) return;
    setFile(f);
    const url = URL.createObjectURL(f);
    previewUrls.current.add(url);
    setPreview((old) => {
      if (old) {
        URL.revokeObjectURL(old);
        previewUrls.current.delete(old);
      }
      return url;
    });
    const img = new Image();
    img.onload = () => setSize({ w: img.naturalWidth, h: img.naturalHeight });
    img.src = url;
  }, []);

  const pickGuides = (files: FileList | null) => {
    const images = Array.from(files ?? []).filter((f) => f.type.startsWith("image/")).slice(0, MAX_GUIDES - guides.length);
    setGuides((current) => [...current, ...images.map(makePreview)]);
  };

  const pickEnding = (f: File | undefined) => {
    if (!f || !f.type.startsWith("image/")) return;
    if (ending) discardPreview(ending);
    setEnding(makePreview(f));
  };

  const create = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.set("story_mode", storyMode);
      form.set("title", storyMode === "manual" ? title.trim() : "");
      form.set("story", storyMode === "manual" ? story.trim() : "");
      form.set("story_prompt", storyMode === "ai" ? storyPrompt.trim() : "");
      form.set("target_seconds", String(seconds));
      form.set("first_frame", file!);
      guides.forEach(({ file: guide }) => form.append("guide_frames", guide));
      if (ending) form.set("final_frame", ending.file);
      return api.createProduction(form);
    },
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ["productions"] });
      navigate(`/p/${p.id}?tab=pipeline`);
    },
  });

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files[0]);
  };

  const words = story.trim() ? story.trim().split(/\s+/).length : 0;
  const ratio = size ? size.w / size.h : null;
  const ratioOk = ratio == null || Math.abs(ratio - 1.5) < 0.12;
  const ready = !!file && (storyMode === "ai" ? storyPrompt.trim().length > 2 : title.trim().length > 1 && story.trim().length >= 20);

  return (
    <>
      <PageHeader
        eyebrow="New production"
        title={startMode === "existing" ? "Build on an existing production" : storyMode === "ai" ? "Give the AI your pictures" : "Start with frames and a story"}
        subtitle={startMode === "existing"
          ? "Choose a production to duplicate. The copy keeps its creative and rendered work but can be edited independently."
          : storyMode === "ai"
            ? "Upload the visual anchors and give one simple direction. The AI will choose the title, characters and complete story."
            : "Choose the opening frame, then optionally add guide frames and a final frame to shape how the production develops."}
      />
      <div className="px-8 pt-7">
        <div role="group" aria-label="Production starting point" className="grid max-w-2xl grid-cols-2 rounded-xl border border-white/[0.08] bg-ink-850 p-1">
          <button
            type="button"
            aria-pressed={startMode === "scratch"}
            onClick={() => setStartMode("scratch")}
            className={clsx("rounded-lg px-4 py-2.5 text-[13px] transition-colors", startMode === "scratch" ? "bg-ink-700 font-medium text-fg shadow" : "text-fg-3 hover:text-fg")}
          >
            Start from scratch
          </button>
          <button
            type="button"
            aria-pressed={startMode === "existing"}
            onClick={() => setStartMode("existing")}
            className={clsx("rounded-lg px-4 py-2.5 text-[13px] transition-colors", startMode === "existing" ? "bg-amber/15 font-medium text-amber shadow" : "text-fg-3 hover:text-fg")}
          >
            Start from an existing production
          </button>
        </div>
      </div>
      {startMode === "scratch" ? (
      <div className="grid gap-6 px-8 py-7 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <section>
          <label
            onDragOver={(e) => (e.preventDefault(), setDragging(true))}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={clsx(
              "group relative flex aspect-[3/2] cursor-pointer flex-col items-center justify-center overflow-hidden rounded-[var(--radius-card)] border transition-all",
              dragging ? "border-amber bg-amber/[0.06]" : preview ? "border-white/[0.08]" : "border-dashed border-white/[0.14] bg-ink-850/60 hover:border-amber/50",
            )}
          >
            <input type="file" accept="image/*" className="sr-only" onChange={(e) => pick(e.target.files?.[0])} />
            {preview ? (
              <>
                <img src={preview} alt="First frame" className="absolute inset-0 h-full w-full object-cover" />
                <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
                <span className="absolute bottom-4 left-1/2 inline-flex -translate-x-1/2 items-center gap-2 rounded-lg bg-black/60 px-3 py-1.5 text-[12px] text-white opacity-0 backdrop-blur transition-opacity group-hover:opacity-100">
                  <RefreshCw className="size-3.5" /> Replace frame
                </span>
              </>
            ) : (
              <>
                <span className="flex size-14 items-center justify-center rounded-2xl border border-white/[0.08] bg-ink-800 text-fg-3 transition-colors group-hover:text-amber">
                  <ImagePlus className="size-6" strokeWidth={1.5} />
                </span>
                <span className="mt-4 text-[14px] font-medium text-fg">Drop the first frame here</span>
                <span className="mt-1 text-[12px] text-fg-3">or click to choose · PNG or JPG · 3:2 landscape works best</span>
              </>
            )}
          </label>
          {file && size && (
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-fg-3">
              <span className="truncate text-fg-2">{file.name}</span>
              <span className="font-mono">
                {size.w}×{size.h}
              </span>
              <span className={ratioOk ? "text-ok" : "text-warn"}>
                {ratioOk ? "3:2 — matches the film frame" : `${ratio!.toFixed(2)}:1 — will be cropped to 3:2`}
              </span>
            </div>
          )}

          <div className="card mt-5 p-4">
            <div>
              <div className="text-[13px] font-medium text-fg">More reference frames <span className="font-normal text-fg-4">· optional</span></div>
              <p className="mt-1 text-[11.5px] leading-relaxed text-fg-3">Guide frames are used in this order across the film. A final frame pins the end of the last shot.</p>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-3 sm:grid-cols-4">
              {guides.map((guide, i) => (
                <div key={guide.preview} className="group relative aspect-[3/2] overflow-hidden rounded-lg border border-white/10 bg-ink-900">
                  <img src={guide.preview} alt={`Guide frame ${i + 1}`} className="h-full w-full object-cover" />
                  <span className="absolute bottom-1.5 left-1.5 rounded bg-black/65 px-1.5 py-0.5 text-[10px] text-white">Guide {i + 1}</span>
                  <button
                    type="button"
                    aria-label={`Remove guide frame ${i + 1}`}
                    onClick={() => { discardPreview(guide); setGuides((current) => current.filter((item) => item !== guide)); }}
                    className="absolute top-1.5 right-1.5 rounded-md bg-black/65 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
                  >
                    <X className="size-3.5" />
                  </button>
                </div>
              ))}
              {guides.length < MAX_GUIDES && (
                <label className="flex aspect-[3/2] cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-white/[0.14] bg-ink-900 text-fg-3 hover:border-amber/50 hover:text-amber">
                  <input type="file" accept="image/*" multiple className="sr-only" onChange={(e) => { pickGuides(e.target.files); e.target.value = ""; }} />
                  <ImagePlus className="size-5" />
                  <span className="mt-1 text-[10.5px]">Add guides</span>
                </label>
              )}
              <label className="group relative flex aspect-[3/2] cursor-pointer flex-col items-center justify-center overflow-hidden rounded-lg border border-dashed border-amber/30 bg-amber/[0.03] text-fg-3 hover:border-amber/60 hover:text-amber">
                <input type="file" accept="image/*" className="sr-only" onChange={(e) => { pickEnding(e.target.files?.[0]); e.target.value = ""; }} />
                {ending ? (
                  <>
                    <img src={ending.preview} alt="Final frame" className="absolute inset-0 h-full w-full object-cover" />
                    <span className="absolute bottom-1.5 left-1.5 rounded bg-black/65 px-1.5 py-0.5 text-[10px] text-white">Final</span>
                    <button
                      type="button"
                      aria-label="Remove final frame"
                      onClick={(e) => { e.preventDefault(); e.stopPropagation(); discardPreview(ending); setEnding(null); }}
                      className="absolute top-1.5 right-1.5 rounded-md bg-black/65 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
                    >
                      <X className="size-3.5" />
                    </button>
                  </>
                ) : (
                  <><Flag className="size-5" /><span className="mt-1 text-[10.5px]">Add final</span></>
                )}
              </label>
            </div>
            <p className="mt-3 text-[10.5px] text-fg-4">Up to {MAX_GUIDES} guides · 25 MB per image</p>
          </div>
        </section>

        <section className="flex flex-col gap-5">
          <div className="card p-5">
            <div>
              <span className="eyebrow">Who creates the story?</span>
              <div role="group" aria-label="Story creation mode" className="mt-2 grid grid-cols-2 rounded-lg border border-white/[0.08] bg-ink-900 p-1">
                <button
                  type="button"
                  aria-pressed={storyMode === "manual"}
                  onClick={() => setStoryMode("manual")}
                  className={clsx("rounded-md px-3 py-2 text-[12.5px] transition-colors", storyMode === "manual" ? "bg-ink-700 font-medium text-fg shadow" : "text-fg-3 hover:text-fg")}
                >
                  I’ll write it
                </button>
                <button
                  type="button"
                  aria-pressed={storyMode === "ai"}
                  onClick={() => setStoryMode("ai")}
                  className={clsx("rounded-md px-3 py-2 text-[12.5px] transition-colors", storyMode === "ai" ? "bg-amber/15 font-medium text-amber shadow" : "text-fg-3 hover:text-fg")}
                >
                  Invent from images
                </button>
              </div>
            </div>

            {storyMode === "manual" ? (
              <>
                <label className="mt-5 block">
                  <span className="eyebrow">Title</span>
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Elio's First Flight"
                    className="mt-2 w-full rounded-lg border border-white/[0.08] bg-ink-900 px-3.5 py-2.5 font-display text-[18px] text-fg placeholder:text-fg-4 focus:border-amber/50 focus:outline-none"
                  />
                </label>
                <label className="mt-5 block">
                  <span className="flex items-baseline justify-between">
                    <span className="eyebrow">Story</span>
                    <span className="font-mono text-[10.5px] text-fg-4">{words} words</span>
                  </span>
                  <textarea
                    value={story}
                    onChange={(e) => setStory(e.target.value)}
                    rows={9}
                    placeholder="Late at night in his cluttered workshop, Elio finishes a small homemade flying machine. At golden hour he takes it to the beach…"
                    className="mt-2 w-full resize-y rounded-lg border border-white/[0.08] bg-ink-900 px-3.5 py-3 text-[13.5px] leading-relaxed text-fg placeholder:text-fg-4 focus:border-amber/50 focus:outline-none"
                  />
                </label>
              </>
            ) : (
              <div className="mt-5">
                <label className="block">
                  <span className="flex items-baseline justify-between">
                    <span className="eyebrow">Creative direction</span>
                    <span className="font-mono text-[10.5px] text-fg-4">{storyPrompt.length}/1200</span>
                  </span>
                  <textarea
                    value={storyPrompt}
                    onChange={(e) => setStoryPrompt(e.target.value.slice(0, 1200))}
                    rows={4}
                    placeholder="Generate an interesting story."
                    className="mt-2 w-full resize-y rounded-lg border border-amber/20 bg-amber/[0.025] px-3.5 py-3 text-[13.5px] leading-relaxed text-fg placeholder:text-fg-4 focus:border-amber/60 focus:outline-none"
                  />
                </label>
                <div className={clsx("mt-3 rounded-lg border px-3.5 py-3 text-[11.5px] leading-relaxed", modelCanInspect ? "border-ok/20 bg-ok/[0.04] text-fg-2" : "border-warn/25 bg-warn/[0.05] text-fg-3")}>
                  {modelCanInspect
                    ? "The vision model will read the references in order and invent a title and story that connects them. You can review the result before planning."
                    : "The current model is text-only, so it will invent the title and story from this direction without seeing the pictures. The pictures will still anchor the video in their uploaded order."}
                </div>
              </div>
            )}
            <div className="mt-5">
              <div className="eyebrow">Target length</div>
              <div className="mt-2 inline-flex rounded-lg border border-white/[0.08] bg-ink-900 p-1">
                {LENGTHS.map((l) => (
                  <button
                    key={l.s}
                    onClick={() => setSeconds(l.s)}
                    className={clsx(
                      "h-8 rounded-md px-3.5 text-[12.5px] transition-colors",
                      seconds === l.s ? "bg-ink-700 font-medium text-fg shadow" : "text-fg-3 hover:text-fg",
                    )}
                  >
                    {l.label}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-[11.5px] text-fg-4">
                About {Math.round(17 + (seconds * 50) / 60)} min on this Mac: ~17 min of planning, then ~50 s of rendering per second of film.
              </p>
            </div>
          </div>

          <div className="card p-5">
            <div className="flex items-center gap-2 text-[13px] font-medium text-fg">
              <Sparkles className="size-4 text-amber" /> What happens next
            </div>
            <ol className="mt-3 flex flex-col">
              {next.map((n, i) => (
                <li key={n.label} className="flex items-center gap-3 border-b border-white/[0.04] py-2 last:border-0">
                  <span className="font-mono text-[10.5px] text-fg-4">{String(i + 1).padStart(2, "0")}</span>
                  <span className="flex-1 text-[12.5px] text-fg-2">{n.label}</span>
                  {n.checkpoint && <Flag className="size-3 text-warn" aria-label="your approval" />}
                  <EngineTag engine={n.engine} />
                </li>
              ))}
            </ol>
          </div>

          {create.error && <p className="text-[12.5px] text-bad">{String(create.error.message)}</p>}
          <Button
            variant="primary"
            size="lg"
            disabled={!ready}
            loading={create.isPending}
            onClick={() => create.mutate()}
            className="self-end"
          >
            {storyMode === "ai" ? (create.isPending ? "Inventing story…" : "Invent story & create") : "Create production"} <ArrowRight className="size-4" />
          </Button>
        </section>
      </div>
      ) : (
        <ExistingProductionStart />
      )}
    </>
  );
}

function ExistingProductionStart() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["productions"], queryFn: api.productions });
  const candidates = (data ?? []).filter((production) => !production.source.startsWith("Stage"));
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [copyTitle, setCopyTitle] = useState("");
  const selected = candidates.find((production) => production.id === sourceId) ?? null;

  useEffect(() => {
    if (!candidates.length || candidates.some((production) => production.id === sourceId)) return;
    const first = candidates.find((production) => !production.active_job) ?? candidates[0];
    setSourceId(first.id);
    setCopyTitle(`${first.title} Copy`);
  }, [data, sourceId]);

  const choose = (production: ProductionSummary) => {
    setSourceId(production.id);
    setCopyTitle(`${production.title} Copy`);
  };
  const duplicate = useMutation({
    mutationFn: () => api.duplicateProduction(selected!.id, copyTitle.trim()),
    onSuccess: (production) => {
      void qc.invalidateQueries({ queryKey: ["productions"] });
      navigate(`/p/${production.id}?tab=pipeline`);
    },
  });
  const ready = !!selected && !selected.active_job && copyTitle.trim().length >= 2;

  return (
    <div className="grid gap-6 px-8 py-7 xl:grid-cols-[minmax(360px,0.9fr)_minmax(0,1.1fr)]">
      <section className="card overflow-hidden">
        <div className="border-b border-white/[0.06] p-5">
          <span className="eyebrow">Choose a starting point</span>
          <p className="mt-1 text-[12px] leading-relaxed text-fg-3">Your original production remains unchanged.</p>
        </div>
        <div className="max-h-[620px] space-y-2 overflow-y-auto p-3">
          {isLoading && [0, 1, 2].map((item) => <div key={item} className="skeleton h-24" />)}
          {error && <p className="p-3 text-[12.5px] text-bad">{error.message}</p>}
          {!isLoading && !error && candidates.length === 0 && (
            <div className="flex min-h-56 flex-col items-center justify-center px-6 text-center">
              <Film className="size-7 text-fg-4" strokeWidth={1.4} />
              <p className="mt-3 text-[13px] font-medium text-fg">No reusable productions yet</p>
              <p className="mt-1 text-[11.5px] text-fg-3">Create one from scratch first, then it can become a starting point.</p>
            </div>
          )}
          {candidates.map((production) => {
            const poster = production.poster ?? production.first_frame;
            const active = production.id === sourceId;
            return (
              <button
                key={production.id}
                type="button"
                disabled={!!production.active_job}
                onClick={() => choose(production)}
                className={clsx(
                  "flex w-full items-center gap-3 rounded-xl border p-2.5 text-left transition-all disabled:cursor-not-allowed disabled:opacity-50",
                  active ? "border-amber/45 bg-amber/[0.07]" : "border-white/[0.06] bg-ink-850 hover:border-white/[0.14] hover:bg-ink-800",
                )}
              >
                <div className="h-[72px] w-[108px] shrink-0 overflow-hidden rounded-lg bg-ink-900">
                  {poster ? <img src={thumbUrl(poster, production.poster ? 1 : 0, 300)} alt="" className="h-full w-full object-cover" /> : <Film className="m-auto size-6 text-fg-4" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-display text-[16px] text-fg">{production.title}</span>
                    {active && <Check className="size-4 shrink-0 text-amber" />}
                  </div>
                  <p className="mt-1 text-[11px] text-fg-3">
                    {production.shots_done ? `${production.shots_done} shots · ${production.takes} takes` : "Planning not started"}
                    {production.film_seconds != null ? ` · finished film` : ""}
                  </p>
                  {production.active_job && <p className="mt-1 text-[10.5px] text-warn">Available when its current job finishes</p>}
                </div>
              </button>
            );
          })}
        </div>
      </section>

      <section className="flex flex-col gap-5">
        <div className="card p-5">
          <div className="flex items-center gap-2 text-[13px] font-medium text-fg">
            <Copy className="size-4 text-amber" /> Create an independent copy
          </div>
          {selected ? (
            <>
              <label className="mt-5 block">
                <span className="eyebrow">New production title</span>
                <input
                  value={copyTitle}
                  onChange={(event) => setCopyTitle(event.target.value)}
                  maxLength={120}
                  className="mt-2 w-full rounded-lg border border-white/[0.08] bg-ink-900 px-3.5 py-2.5 font-display text-[18px] text-fg focus:border-amber/50 focus:outline-none"
                />
              </label>
              <div className="mt-5 rounded-xl border border-white/[0.07] bg-ink-900 p-4">
                <p className="text-[12.5px] font-medium text-fg">Copied from “{selected.title}”</p>
                <ul className="mt-3 grid gap-2 text-[11.5px] text-fg-2 sm:grid-cols-2">
                  {["Story and visual references", "Shot plan and timeline", "Voices and approved choices", "Takes and finished film"].map((label) => (
                    <li key={label} className="flex items-center gap-2"><Check className="size-3.5 text-ok" /> {label}</li>
                  ))}
                </ul>
              </div>
              <div className="mt-4 flex gap-3 rounded-lg border border-info/20 bg-info/[0.04] p-3 text-[11.5px] leading-relaxed text-fg-3">
                <HardDrive className="mt-0.5 size-4 shrink-0 text-info" />
                Media files are copied so future edits and deletion are independent. The new production will use roughly the same disk space as the original.
              </div>
            </>
          ) : (
            <div className="flex min-h-72 items-center justify-center text-[12.5px] text-fg-4">Choose a production to continue.</div>
          )}
        </div>
        {duplicate.error && <p role="alert" className="text-[12.5px] text-bad">{duplicate.error.message}</p>}
        <Button
          variant="primary"
          size="lg"
          icon={<Copy className="size-4" />}
          disabled={!ready}
          loading={duplicate.isPending}
          onClick={() => duplicate.mutate()}
          className="self-end"
        >
          Create from this production
        </Button>
      </section>
    </div>
  );
}
