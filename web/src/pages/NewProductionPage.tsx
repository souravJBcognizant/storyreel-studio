import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, Flag, ImagePlus, RefreshCw, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router";
import { PageHeader } from "../components/AppShell";
import { Button, EngineTag } from "../components/ui";
import { api, type Engine } from "../lib/api";

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
  const [title, setTitle] = useState("");
  const [story, setStory] = useState("");
  const [seconds, setSeconds] = useState(60);
  const [dragging, setDragging] = useState(false);
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  // Nested optional checks keep this page usable while Vite and the API reload at different times.
  const planningEngine: Engine = settings?.providers.language?.provider === "ollama" ? "ollama" : "claude";
  const imageEngine: Engine = settings?.providers.images?.provider === "local" ? "local" : "openai";
  const next: { label: string; engine: Engine; checkpoint?: boolean }[] = settings?.mode === "local"
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
      form.set("title", title.trim());
      form.set("story", story.trim());
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
  const ready = !!file && title.trim().length > 1 && story.trim().length >= 20;

  return (
    <>
      <PageHeader
        eyebrow="New production"
        title="Start with frames and a story"
        subtitle="Choose the opening frame, then optionally add guide frames and a final frame to shape how the production develops."
      />
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
            <label className="block">
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
            Create production <ArrowRight className="size-4" />
          </Button>
        </section>
      </div>
    </>
  );
}
