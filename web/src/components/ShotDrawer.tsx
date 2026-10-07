import * as Dialog from "@radix-ui/react-dialog";
import clsx from "clsx";
import { Check, Crown, Mic, MicOff, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { Scene, Shot, Take } from "../lib/api";
import { mediaUrl, thumbUrl } from "../lib/api";
import { duration } from "../lib/format";
import { ScoreChip, StatusPill } from "./ui";
import { VideoPlayer } from "./VideoPlayer";

export function ShotDrawer({
  shot,
  scene,
  onClose,
}: {
  shot: Shot | null;
  scene: Scene | null;
  onClose: () => void;
}) {
  const [takeIndex, setTakeIndex] = useState<number | null>(null);
  const [original, setOriginal] = useState(false); // dubbed takes: hear LTX's own voice instead of the cast voice
  useEffect(() => setTakeIndex(shot?.chosen ?? (shot?.takes.length ? shot.takes.length - 1 : null)), [shot?.id, shot?.chosen, shot?.takes.length]);
  const take = shot && takeIndex != null ? shot.takes.find((t) => t.index === takeIndex) ?? null : null;
  const src = take ? (take.dub && !original ? take.dub : take.path) : null;

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
                  <VideoPlayer key={src} src={mediaUrl(src)} poster={thumbUrl(take.path, 0.5, 960)} className="aspect-[3/2] w-full" autoPlay />
                ) : (
                  <div className="skeleton aspect-[3/2] w-full" />
                )}
                {take?.dub && (
                  <div className="mt-3 flex items-center gap-3">
                    <div className="inline-flex rounded-lg border border-white/[0.08] bg-ink-850 p-0.5 text-[12px]">
                      {[
                        { on: false, icon: <Mic className="size-3.5" />, label: shot.delivery === "off" ? "Cast voice, laid over" : "Cast voice, dubbed" },
                        { on: true, icon: <MicOff className="size-3.5" />, label: "LTX original" },
                      ].map((o) => (
                        <button
                          key={o.label}
                          onClick={() => setOriginal(o.on)}
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
                      {shot.delivery === "off" ? "Heard off screen over this picture." : "The cast voice, word by word on LTX's lip movements."}
                    </span>
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
            <span title="Words of the cast voice placed on LTX's lip movements" className="inline-flex h-[22px] items-center gap-1 rounded-md border border-white/[0.08] bg-white/[0.03] px-1.5 font-mono text-[10.5px] text-fg-2">
              <span className="font-sans text-fg-3">Lips</span> {take.dub_words}
            </span>
          )}
          <ScoreChip metric="voice" value={take.voice} info={dubbed} />
          {shot.identity_check && <ScoreChip metric="identity" value={take.identity} info={dubbed} />}
          <ScoreChip metric="continuity" value={take.continuity} info={dubbed} />
        </div>
        {take.heard && <div className="mt-1 truncate text-[11px] text-fg-3">{dubbed ? "LTX said" : "Heard"}: “{take.heard}”</div>}
      </div>
      <div className="shrink-0 text-right font-mono text-[10.5px] text-fg-3">
        <div>{take.seconds.toFixed(1)} s</div>
        <div className="text-fg-4">{take.cached ? "cached" : duration(take.render_s)}</div>
      </div>
    </button>
  );
}
