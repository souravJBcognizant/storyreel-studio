import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AudioLines, Check, Clapperboard, Crown, Mic, MicOff, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { Scene, Shot, Take } from "../lib/api";
import { api, mediaUrl, thumbUrl } from "../lib/api";
import { duration } from "../lib/format";
import { Button, ScoreChip, StatusPill } from "./ui";
import { VideoPlayer } from "./VideoPlayer";

export function ShotDrawer({
  shot,
  scene,
  productionId,
  busy,
  onClose,
}: {
  shot: Shot | null;
  scene: Scene | null;
  productionId: string;
  busy: boolean;
  onClose: () => void;
}) {
  const [takeIndex, setTakeIndex] = useState<number | null>(null);
  const [original, setOriginal] = useState(false); // dubbed takes: hear LTX's own voice instead of the cast voice
  const [clipPrompt, setClipPrompt] = useState("");
  const [audioPrompt, setAudioPrompt] = useState("");
  const qc = useQueryClient();
  const choice = useMutation({
    mutationFn: ({ id, source }: { id: string; source: "cast" | "original" }) => api.chooseAudio(productionId, id, source),
    onSuccess: (p) => qc.setQueryData(["production", productionId], p),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["production", productionId] });
    void qc.invalidateQueries({ queryKey: ["jobs"] });
  };
  const regenerateClip = useMutation({
    mutationFn: () => api.regenerateShot(productionId, shot!.id, clipPrompt.trim()),
    onSuccess: refresh,
  });
  const regenerateAudio = useMutation({
    mutationFn: () => api.regenerateOverlay(productionId, shot!.id, audioPrompt.trim()),
    onSuccess: refresh,
  });
  const editPending = regenerateClip.isPending || regenerateAudio.isPending;
  useEffect(() => {
    setOriginal(shot?.audio_source === "original");
    setClipPrompt("");
    setAudioPrompt("");
    choice.reset();
    regenerateClip.reset();
    regenerateAudio.reset();
  }, [shot?.id, shot?.audio_source]);
  useEffect(() => setTakeIndex(shot?.chosen ?? (shot?.takes.length ? shot.takes.length - 1 : null)), [shot?.id, shot?.chosen, shot?.takes.length]);
  const take = shot && takeIndex != null ? shot.takes.find((t) => t.index === takeIndex) ?? null : null;
  const src = take ? (take.dub && !original ? `${mediaUrl(take.dub)}?v=${take.dub_revision ?? 0}` : mediaUrl(take.path)) : null;

  return (
    <Dialog.Root open={!!shot} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 backdrop-blur-[2px] data-[state=open]:animate-[rise_0.2s_ease-out]" />
        <Dialog.Content
          className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[720px] flex-col border-l border-white/[0.08] bg-ink-900 shadow-[var(--shadow-pop)] outline-none"
          aria-describedby={undefined}
          onOpenAutoFocus={(e) => e.preventDefault()}
        >
          {shot && (
            <>
              <header className="flex items-start justify-between gap-4 border-b border-white/[0.06] px-6 py-4">
                <div className="min-w-0">
                  <div className="eyebrow">
                    Scene · {scene?.id} — {shot.start === "continue" ? `continues ${shot.from}` : shot.start === "anchor" ? "anchored on reference" : "new shot"}
                  </div>
                  <Dialog.Title className="mt-1 flex items-center gap-2.5 font-display text-[22px] text-fg">
                    Shot {shot.id}
                    <StatusPill status={shot.status} />
                  </Dialog.Title>
                </div>
                <Dialog.Close className="rounded-lg p-1.5 text-fg-3 hover:bg-white/[0.06] hover:text-fg" aria-label="Close">
                  <X className="size-5" />
                </Dialog.Close>
              </header>

              <div className="flex-1 overflow-y-auto px-6 py-5">
                {take && src ? (
                  <VideoPlayer key={src} src={src} poster={thumbUrl(take.path, 0.5, 960)} className="aspect-[3/2] w-full" autoPlay />
                ) : (
                  <div className="skeleton aspect-[3/2] w-full" />
                )}
                {take?.dub && (
                  <div className="mt-3 flex items-center gap-3">
                    <div className="inline-flex rounded-lg border border-white/[0.08] bg-ink-850 p-0.5 text-[12px]">
                      {[
                        { on: false, icon: <Mic className="size-3.5" />, label: "Overlay audio" },
                        { on: true, icon: <MicOff className="size-3.5" />, label: "Original audio" },
                      ].map((o) => (
                        <button
                          key={o.label}
                          onClick={() => setOriginal(o.on)}
                          aria-pressed={original === o.on}
                          className={clsx(
                            "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 transition-colors",
                            original === o.on ? "bg-white/[0.08] text-fg" : "text-fg-3 hover:text-fg-2",
                          )}
                        >
                          {o.icon} {o.label}
                        </button>
                      ))}
                    </div>
                    <span className="text-[11.5px] text-fg-4">
                      Preview audio
                    </span>
                  </div>
                )}

                {shot.has_cast_audio && shot.chosen != null && (
                  <div className="mt-4 rounded-lg border border-white/[0.08] bg-ink-850 p-3">
                    <label className="flex items-center justify-between gap-3 text-[12px] text-fg-2">
                      Audio in exported film
                      <select
                        aria-label="Audio in exported film"
                        value={shot.audio_source}
                        disabled={busy || choice.isPending || editPending}
                        onChange={(e) => choice.mutate({ id: shot.id, source: e.target.value as "cast" | "original" })}
                        className="rounded-md border border-white/10 bg-ink-900 px-3 py-2 text-fg disabled:opacity-50"
                      >
                        <option value="cast">Overlay audio</option>
                        <option value="original">Original audio</option>
                      </select>
                    </label>
                    <p className="mt-2 text-[11.5px] text-fg-3">
                      {choice.isPending ? "Saving…" : `Saved for this shot’s chosen take (${shot.chosen + 1}). Rebuild the film in the Film tab to apply your choices.`}
                    </p>
                    {choice.error && <p role="alert" className="mt-2 text-[12px] text-bad">{choice.error.message}</p>}
                  </div>
                )}

                <div className="mt-5 grid gap-1 text-[13px] leading-relaxed">
                  <p className="text-fg-2">{shot.action}</p>
                  {shot.line && (
                    <p className="text-fg">
                      <span className="text-fg-3">{shot.delivery === "off" ? `Off camera · ${name(shot.speaker)} · ` : "Line · "}</span>“{shot.line}”
                    </p>
                  )}
                  {shot.camera && <p className="text-fg-3">{shot.camera}</p>}
                </div>

                {shot.chosen != null && (
                  <div className="mt-6 grid gap-3 sm:grid-cols-2">
                    <form
                      className="rounded-xl border border-white/[0.08] bg-ink-850 p-3"
                      onSubmit={(e) => { e.preventDefault(); if (clipPrompt.trim().length >= 3) regenerateClip.mutate(); }}
                    >
                      <div className="flex items-center gap-2 text-[12.5px] font-medium text-fg">
                        <Clapperboard className="size-4 text-amber" /> Generate a new clip
                      </div>
                      <p className="mt-1 text-[11.5px] leading-relaxed text-fg-3">Describe what should change. A new take is generated and the film is rebuilt.</p>
                      <textarea
                        aria-label="Direction for new clip"
                        value={clipPrompt}
                        onChange={(e) => setClipPrompt(e.target.value)}
                        maxLength={600}
                        rows={3}
                        placeholder="Make the gesture smaller and hold eye contact with the audience."
                        className="mt-3 w-full resize-y rounded-lg border border-white/10 bg-ink-900 px-3 py-2 text-[12px] leading-relaxed text-fg outline-none placeholder:text-fg-4 focus:border-amber/50"
                      />
                      <Button type="submit" size="sm" className="mt-2 w-full" loading={regenerateClip.isPending} disabled={busy || editPending || clipPrompt.trim().length < 3}>
                        Generate clip
                      </Button>
                      {regenerateClip.error && <p role="alert" className="mt-2 text-[11.5px] text-bad">{regenerateClip.error.message}</p>}
                    </form>

                    {shot.has_cast_audio && (
                      <form
                        className="rounded-xl border border-white/[0.08] bg-ink-850 p-3"
                        onSubmit={(e) => { e.preventDefault(); if (audioPrompt.trim().length >= 3) regenerateAudio.mutate(); }}
                      >
                        <div className="flex items-center gap-2 text-[12.5px] font-medium text-fg">
                          <AudioLines className="size-4 text-amber" /> Regenerate overlay audio
                        </div>
                        <p className="mt-1 text-[11.5px] leading-relaxed text-fg-3">Describe the delivery. The scripted words stay unchanged and the result is synced to the original performance.</p>
                        <textarea
                          aria-label="Direction for overlay audio"
                          value={audioPrompt}
                          onChange={(e) => setAudioPrompt(e.target.value)}
                          maxLength={600}
                          rows={3}
                          placeholder="Quieter and more hesitant, with a longer pause before the final sentence."
                          className="mt-3 w-full resize-y rounded-lg border border-white/10 bg-ink-900 px-3 py-2 text-[12px] leading-relaxed text-fg outline-none placeholder:text-fg-4 focus:border-amber/50"
                        />
                        <Button type="submit" size="sm" className="mt-2 w-full" loading={regenerateAudio.isPending} disabled={busy || editPending || audioPrompt.trim().length < 3}>
                          Generate audio
                        </Button>
                        {regenerateAudio.error && <p role="alert" className="mt-2 text-[11.5px] text-bad">{regenerateAudio.error.message}</p>}
                      </form>
                    )}
                  </div>
                )}

                <h4 className="eyebrow mt-6 mb-2">Takes</h4>
                <div className="flex flex-col gap-2">
                  {shot.takes.map((t) => (
                    <TakeRow key={t.index} take={t} chosen={t.index === shot.chosen} active={t.index === takeIndex} shot={shot} onPick={() => setTakeIndex(t.index)} />
                  ))}
                  {shot.status === "rendering" && (
                    <div className="flex items-center gap-3 rounded-xl border border-dashed border-amber/40 bg-amber/[0.04] px-4 py-3 text-[12.5px] text-amber">
                      <span className="size-2 animate-pulse-soft rounded-full bg-amber" /> Rendering take {(shot.current_take ?? 0) + 1}…
                    </div>
                  )}
                  {!shot.takes.length && shot.status === "pending" && <p className="text-[12.5px] text-fg-3">Not rendered yet.</p>}
                </div>

                {take?.contact && (
                  <>
                    <h4 className="eyebrow mt-6 mb-2">Contact sheet · take {take.index + 1}</h4>
                    <img src={mediaUrl(take.contact)} alt="" className="w-full rounded-lg border border-white/[0.06]" />
                  </>
                )}

                {shot.prompt && (
                  <details className="group mt-6">
                    <summary className="eyebrow cursor-pointer list-none select-none hover:text-fg-2">
                      <span className="group-open:hidden">▸</span>
                      <span className="hidden group-open:inline">▾</span> Prompt sent to LTX
                    </summary>
                    <p className="mt-2 rounded-lg border border-white/[0.06] bg-ink-850 p-3 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-fg-2">
                      {shot.prompt}
                    </p>
                  </details>
                )}
              </div>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function name(id: string | null) {
  return id ? id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "someone";
}

function TakeRow({ take, shot, chosen, active, onPick }: { take: Take; shot: Shot; chosen: boolean; active: boolean; onPick: () => void }) {
  const dubbed = take.dub != null;
  const speakerFailed = take.failures.some((f) => /speaker|someone/.test(f));
  return (
    <button
      onClick={onPick}
      className={clsx(
        "flex w-full items-center gap-3 rounded-xl border p-2 text-left transition-colors",
        active ? "border-amber/40 bg-amber/[0.05]" : "border-white/[0.06] bg-ink-850 hover:border-white/[0.12]",
      )}
    >
      <img src={thumbUrl(take.path, 1.2, 240)} alt="" className="aspect-[3/2] w-[92px] shrink-0 rounded-md object-cover" loading="lazy" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[12.5px] font-medium text-fg">
          Take {take.index + 1}
          {chosen && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber">
              <Crown className="size-3" /> in the film
            </span>
          )}
          <span className="font-mono text-[10.5px] font-normal text-fg-4">seed {take.seed}</span>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {take.passed ? (
            <span className="inline-flex items-center gap-1 text-[11px] text-ok">
              <Check className="size-3" /> passed
            </span>
          ) : (
            <span className="text-[11px] text-bad">failed: {take.failures.join(", ")}</span>
          )}
          <span className="mx-1 text-fg-4">·</span>
          <ScoreChip metric="words" value={take.wer} />
          {take.speaker && (
            <span
              title={take.speaker_note ?? undefined}
              className={clsx(
                "inline-flex h-[22px] items-center gap-1 rounded-md border px-1.5 text-[10.5px]",
                speakerFailed ? "border-bad/25 bg-bad/[0.08] text-bad" : "border-ok/20 bg-ok/[0.07] text-ok",
              )}
            >
              <span className="text-fg-3">Talking</span> {take.speaker}
            </span>
          )}
          {take.dub_words && (
            <span title="Words matched between the original and overlay recordings to align their timing" className="inline-flex h-[22px] items-center gap-1 rounded-md border border-white/[0.08] bg-white/[0.03] px-1.5 font-mono text-[10.5px] text-fg-2">
              <span className="font-sans text-fg-3">Timing</span> {take.dub_words}
            </span>
          )}
          <ScoreChip metric="voice" value={take.voice} info={dubbed} />
          {shot.identity_check && <ScoreChip metric="identity" value={take.identity} info={dubbed} />}
          <ScoreChip metric="continuity" value={take.continuity} info={dubbed} />
        </div>
        {take.heard && <div className="mt-1 truncate text-[11px] text-fg-3">{dubbed ? "Original speech" : "Heard"}: “{take.heard}”</div>}
        {take.edit_prompt && <div className="mt-1 line-clamp-2 text-[11px] text-fg-3">Clip direction: “{take.edit_prompt}”</div>}
        {take.audio_prompt && <div className="mt-1 line-clamp-2 text-[11px] text-fg-3">Audio direction: “{take.audio_prompt}”</div>}
      </div>
      <div className="shrink-0 text-right font-mono text-[10.5px] text-fg-3">
        <div>{take.seconds.toFixed(1)} s</div>
        <div className="text-fg-4">{take.cached ? "cached" : duration(take.render_s)}</div>
      </div>
    </button>
  );
}
