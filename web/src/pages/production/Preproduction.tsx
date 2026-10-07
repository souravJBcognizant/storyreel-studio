import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Bot, Check, Crown, Mic, Pause, Play, RotateCcw, Sparkles, Wand2, X } from "lucide-react";
import { Link } from "react-router";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button, ProgressBar, StatusPill } from "../../components/ui";
import { api, mediaUrl, thumbUrl, type KeyframeChoice, type Production } from "../../lib/api";
import { ago, duration, pct } from "../../lib/format";

// ---------------------------------------------------------------- the one next action

export function NextStep({ p }: { p: Production }) {
  const qc = useQueryClient();
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["production", p.id] });
    void qc.invalidateQueries({ queryKey: ["jobs"] });
  };
  const start = useMutation({ mutationFn: (kind: "preprod" | "audition" | "render") => api.startJob(p.id, kind), onSuccess: refresh });
  const approve = useMutation({
    mutationFn: async (stages: ("plan" | "keyframes" | "voice")[]) => {
      for (const s of stages) await api.approve(p.id, s);
    },
    onSuccess: refresh,
  });
  const job = p.active_job;
  const steps = p.steps;
  const error = start.error?.message ?? approve.error?.message;

  let body: ReactNode = null;
  if (job && job.kind === "preprod") {
    const a = p.agent_progress;
    body = (
      <Callout tone="live" icon={<Bot className="size-4" />} eyebrow="Agents at work" title={a?.agent ? `${a.agent} is working` : "Starting the Director…"}>
        {a?.last_text && <p className="mt-2 line-clamp-3 text-[12.5px] leading-relaxed text-fg-3">“{a.last_text}”</p>}
        <p className="mt-2 text-[11.5px] text-fg-4">
          {a?.tool ? `Using ${a.tool} · ` : ""}
          {a ? `started ${ago(a.started)}${a.cost ? ` · Claude $${a.cost.toFixed(2)} so far` : ""}` : "Claude plans; OpenAI draws the sheets and keyframes."} You can leave this page — it keeps going.
        </p>
        <Link to={`/p/${p.id}?tab=agents`} className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-amber/30 bg-amber/10 px-3 py-1.5 text-[12.5px] font-medium text-amber hover:bg-amber/15">
          <Bot className="size-3.5" /> Watch the agents work
        </Link>
      </Callout>
    );
  } else if (job && job.kind === "casting") {
    body = (
      <Callout tone="live" icon={<Mic className="size-4" />} eyebrow="Voice casting" title="Designing a new voice">
        <p className="mt-2 text-[12.5px] text-fg-3">Qwen3-TTS is speaking the reference text in the new voice. About 20 seconds.</p>
      </Callout>
    );
  } else if (job && job.kind === "audition") {
    const prog = p.agent_progress as unknown as { shots_done?: number; shots_total?: number; current_shot?: string } | null;
    body = (
      <Callout tone="live" icon={<Mic className="size-4" />} eyebrow="Voice audition" title={prog?.current_shot ? `Recording line ${prog.current_shot}` : "Rendering test lines"}>
        <ProgressBar value={prog?.shots_total ? pct(prog.shots_done ?? 0, prog.shots_total) : 0} live className="mt-3 max-w-md" />
      </Callout>
    );
  } else if (job) {
    body = null; // renders have their own live panel
  } else if (p.can_plan && !p.preprod?.cast) {
    body = (
      <Callout tone="action" icon={<Wand2 className="size-4" />} eyebrow="Next step" title="Plan the film with the agents">
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-fg-3">
          The Director's team reads your story and first frame, writes the screenplay, draws consistent character, prop and scene
          frames, and builds the shot plan. About 10–20 minutes; you approve the result before anything renders.
        </p>
        <Button variant="primary" className="mt-4" icon={<Sparkles className="size-4" />} loading={start.isPending} onClick={() => start.mutate("preprod")}>
          Plan with agents
        </Button>
      </Callout>
    );
  } else if (steps.plan === "awaiting_approval" || steps.keyframes === "awaiting_approval") {
    body = (
      <Callout tone="approve" icon={<Check className="size-4" />} eyebrow="Your approval" title="Review the plan and the scene keyframes">
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-fg-3">
          Check the screenplay in the Plan tab and the keyframes below: these frames open every scene, so the character's look is decided here.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" icon={<Check className="size-4" />} loading={approve.isPending} onClick={() => approve.mutate(["plan", "keyframes"])}>
            Approve plan & keyframes
          </Button>
          {p.can_plan && (
            <Button icon={<RotateCcw className="size-4" />} loading={start.isPending} onClick={() => start.mutate("preprod")}>
              Ask the agents to redo it
            </Button>
          )}
        </div>
      </Callout>
    );
  } else if (steps.voice === "awaiting_approval" && p.preprod?.voices) {
    body = (
      <Callout tone="approve" icon={<Mic className="size-4" />} eyebrow="Your approval" title="Listen to the cast voices">
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-fg-3">
          Every line in the film is spoken in these voices, timed to the actors' lips. Recast any voice that doesn't fit.
        </p>
        <VoicesPanel p={p} compact />
        <Button variant="primary" className="mt-4" icon={<Check className="size-4" />} loading={approve.isPending} onClick={() => approve.mutate(["voice"])}>
          Approve the voices
        </Button>
      </Callout>
    );
  } else if (steps.voice === "awaiting_approval" && p.preprod?.voice) {
    const v = p.preprod.voice;
    body = (
      <Callout tone="approve" icon={<Mic className="size-4" />} eyebrow="Your approval" title={`Is this ${v.character}'s voice?`}>
        <p className="mt-1.5 text-[12.5px] text-fg-3">
          Approved lines become the reference every later line is checked against.
          {v.consistency != null && ` The ${v.clips.length} clips agree at ${v.consistency.toFixed(2)} (0.78 or more is the same voice).`}
        </p>
        <VoiceClips p={p} compact />
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" icon={<Check className="size-4" />} loading={approve.isPending} onClick={() => approve.mutate(["voice"])}>
            Approve this voice
          </Button>
          <Button icon={<RotateCcw className="size-4" />} loading={start.isPending} onClick={() => start.mutate("audition")}>
            Audition again
          </Button>
        </div>
      </Callout>
    );
  } else if (p.can_audition && steps.plan === "done" && steps.keyframes === "done") {
    body = (
      <Callout tone="action" icon={<Mic className="size-4" />} eyebrow="Next step" title="Audition the voice">
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-fg-3">
          Renders the main character's first lines (about 3 minutes each) so you can hear the voice before the film is made.
        </p>
        <Button variant="primary" className="mt-4" icon={<Mic className="size-4" />} loading={start.isPending} onClick={() => start.mutate("audition")}>
          Start the audition
        </Button>
      </Callout>
    );
  } else if (p.can_render && !p.film) {
    body = (
      <Callout tone="action" icon={<Sparkles className="size-4" />} eyebrow="Next step" title="Everything is approved — render the film">
        <Button variant="primary" className="mt-4" loading={start.isPending} onClick={() => start.mutate("render")}>
          Render film
        </Button>
      </Callout>
    );
  }
  if (!body) return null;
  return (
    <>
      {body}
      {error && <p className="-mt-4 text-[12.5px] text-bad">{error}</p>}
    </>
  );
}

function Callout({
  tone,
  icon,
  eyebrow,
  title,
  children,
}: {
  tone: "live" | "action" | "approve";
  icon: ReactNode;
  eyebrow: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <section
      className={clsx(
        "card animate-rise relative overflow-hidden p-5",
        tone === "live" && "border-amber/25",
        tone === "approve" && "border-warn/30",
        tone === "action" && "border-amber/20",
      )}
    >
      <div
        className={clsx(
          "pointer-events-none absolute inset-0",
          tone === "approve" ? "bg-[radial-gradient(600px_200px_at_0%_0%,rgb(232_193_84/0.09),transparent)]" : "bg-[radial-gradient(600px_200px_at_0%_0%,rgb(243_169_60/0.09),transparent)]",
        )}
      />
      <div className="relative">
        <div className={clsx("eyebrow flex items-center gap-2", tone === "approve" ? "text-warn" : "text-amber")}>
          {tone === "live" ? <span className="size-1.5 animate-pulse-soft rounded-full bg-amber" /> : icon} {eyebrow}
        </div>
        <h3 className="mt-1.5 font-display text-[21px] text-fg">{title}</h3>
        {children}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- stage contents

export function CastPanel({ p }: { p: Production }) {
  const cast = p.preprod?.cast;
  if (!cast) return null;
  return (
    <div className="mt-1 grid gap-3 md:grid-cols-2">
      {cast.characters.map((c) => (
        <div key={c.id} className="rounded-xl border border-white/[0.06] bg-ink-900/60 p-3.5">
          <div className="flex items-baseline gap-2">
            <span className="font-display text-[16px] text-fg">{c.name}</span>
            <span className="font-mono text-[10.5px] text-fg-4">{c.id}</span>
          </div>
          <p className="mt-1.5 text-[12px] leading-relaxed text-fg-2">{c.bible}</p>
          <p className="mt-2 text-[11.5px] text-fg-3">
            Voice · <span className="text-fg-2">“{c.voice_phrase}”</span>
          </p>
        </div>
      ))}
      {Object.keys(cast.props).length > 0 && (
        <div className="rounded-xl border border-white/[0.06] bg-ink-900/60 p-3.5">
          <div className="eyebrow mb-2">Props</div>
          {Object.entries(cast.props).map(([k, v]) => (
            <p key={k} className="mb-1.5 text-[12px] leading-relaxed text-fg-2">
              <span className="font-mono text-[11px] text-fg-3">{k}</span> — {v}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

export function SheetsPanel({ p }: { p: Production }) {
  const kf = p.preprod?.keyframes;
  const sheets = [...Object.entries(kf?.sheets ?? {}), ...Object.entries(kf?.props ?? {})];
  if (!sheets.length) return null;
  return (
    <div className="mt-1 grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3">
      {sheets.map(([k, path]) => (
        <a key={k} href={mediaUrl(path)} target="_blank" rel="noreferrer" className="group overflow-hidden rounded-xl border border-white/[0.06] bg-ink-900">
          <img src={thumbUrl(path, 0, 640)} alt="" className="aspect-[3/2] w-full object-cover transition-transform duration-500 group-hover:scale-[1.03]" />
          <div className="px-3 py-2 font-mono text-[11px] text-fg-3">{k}</div>
        </a>
      ))}
    </div>
  );
}

export function KeyframesPanel({ p }: { p: Production }) {
  const scenes = p.preprod?.keyframes?.scenes ?? {};
  const ids = Object.keys(scenes);
  if (!ids.length) return null;
  const names = Object.fromEntries((p.preprod?.cast?.characters ?? []).map((c) => [c.id, c.name]));
  return (
    <div className="mt-1 flex flex-col gap-6">
      {ids.map((sid) => (
        <div key={sid}>
          <div className="mb-2 flex items-center gap-2">
            <span className="font-display text-[15px] text-fg capitalize">{sid.replace(/[-_]/g, " ")}</span>
            <span className="text-[11px] text-fg-4">
              establishing frame{Object.keys(scenes[sid].singles ?? {}).length ? ` + ${Object.keys(scenes[sid].singles ?? {}).length} single(s)` : ""}
            </span>
          </div>
          <CandidateGrid label="Establishing" choice={scenes[sid]} />
          {Object.entries(scenes[sid].singles ?? {}).map(([cid, choice]) => (
            <CandidateGrid key={cid} label={`Single · ${names[cid] ?? cid}`} choice={choice} />
          ))}
        </div>
      ))}
    </div>
  );
}

function CandidateGrid({ label, choice }: { label: string; choice: KeyframeChoice }) {
  return (
    <div className="mt-2">
      <div className="mb-1.5 text-[11px] text-fg-3">
        {label} <span className="text-fg-4">· {choice.candidates.length} candidate(s)</span>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-3">
        {choice.candidates.map((c) => {
          const chosen = choice.chosen === c.n;
          const ids = Object.values(c.identity ?? {}).filter((v): v is number => v != null);
          return (
            <div key={c.n} className={clsx("overflow-hidden rounded-xl border bg-ink-900", chosen ? "border-amber/50 ring-2 ring-amber/15" : "border-white/[0.06] opacity-80")}>
              <a href={mediaUrl(c.frame)} target="_blank" rel="noreferrer" className="relative block">
                <img src={thumbUrl(c.frame, 0, 640)} alt="" className="aspect-[3/2] w-full object-cover" />
                {chosen && (
                  <span className="absolute top-2 left-2 inline-flex items-center gap-1 rounded-full bg-amber px-2 py-0.5 text-[10.5px] font-semibold text-ink-950">
                    <Crown className="size-3" /> chosen
                  </span>
                )}
                <span className="absolute top-2 right-2 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[10px] text-white/85">v{c.n}</span>
              </a>
              <div className="p-3">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className={clsx("inline-flex items-center gap-1 text-[11px]", c.review.same_character ? "text-ok" : "text-bad")}>
                    {c.review.same_character ? <Check className="size-3" /> : <X className="size-3" />} same character
                  </span>
                  <span className="font-mono text-[10.5px] text-fg-3">review {c.review.score}/10</span>
                  {ids.length > 0 && <span className="font-mono text-[10.5px] text-fg-3">· look {Math.min(...ids).toFixed(2)}</span>}
                </div>
                <p className="mt-1.5 line-clamp-3 text-[11.5px] leading-snug text-fg-3">{c.review.verdict}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- cast voices

export function VoicesPanel({ p, compact }: { p: Production; compact?: boolean }) {
  const voices = p.preprod?.voices;
  if (!voices) return null;
  const names = Object.fromEntries((p.preprod?.cast?.characters ?? []).map((c) => [c.id, c.name]));
  return (
    <div className={clsx("grid gap-3", compact ? "mt-4 md:grid-cols-2" : "mt-1 md:grid-cols-2 xl:grid-cols-3")}>
      {Object.entries(voices).map(([cid, v]) => (
        <VoiceCard key={cid} p={p} cid={cid} name={names[cid] ?? cid} voice={v} names={names} />
      ))}
    </div>
  );
}

function VoiceCard({
  p,
  cid,
  name,
  voice,
  names,
}: {
  p: Production;
  cid: string;
  name: string;
  voice: NonNullable<NonNullable<Production["preprod"]>["voices"]>[string];
  names: Record<string, string>;
}) {
  const qc = useQueryClient();
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["production", p.id] });
    void qc.invalidateQueries({ queryKey: ["jobs"] });
  };
  const chosen = voice.candidates.find((c) => c.n === voice.chosen) ?? voice.candidates[voice.candidates.length - 1];
  const [editing, setEditing] = useState(false);
  const [description, setDescription] = useState(chosen?.description ?? "");
  const [text, setText] = useState(chosen?.text ?? "");
  useEffect(() => {
    setDescription(chosen?.description ?? "");
    setText(chosen?.text ?? "");
  }, [chosen?.n, chosen?.description, chosen?.text]);
  const recast = useMutation({ mutationFn: () => api.recastVoice(p.id, cid, description, text), onSuccess: () => (setEditing(false), refresh()) });
  const choose = useMutation({ mutationFn: (n: number) => api.chooseVoice(p.id, cid, n), onSuccess: refresh });
  const busy = !!p.active_job;
  if (!chosen) return null;
  const alike = Object.entries(chosen.likeness).sort((a, b) => b[1] - a[1]);
  return (
    <div className="rounded-xl border border-white/[0.06] bg-ink-900/70 p-3.5">
      <div className="flex items-center gap-3">
        <PlayButton src={mediaUrl(chosen.path)} />
        <div className="min-w-0 flex-1">
          <div className="truncate font-display text-[16px] text-fg">{name}</div>
          <div className="font-mono text-[10.5px] text-fg-4">
            v{chosen.n} · {chosen.seconds.toFixed(1)} s
          </div>
        </div>
      </div>
      <p className="mt-2.5 text-[11.5px] leading-snug text-fg-3">{chosen.description}</p>
      <p className="mt-2 text-[12px] leading-relaxed text-fg-2">“{chosen.text}”</p>
      {alike.length > 0 && (
        <p className="mt-2 text-[11px] text-fg-4">
          Likeness to the others:{" "}
          {alike.map(([o, s], i) => (
            <span key={o} className={clsx("font-mono", s > 0.8 ? "text-bad" : "text-fg-3")}>
              {i ? ", " : ""}
              {names[o] ?? o} {s.toFixed(2)}
            </span>
          ))}{" "}
          <span className="text-fg-4">(one voice scores 0.85+)</span>
        </p>
      )}
      {voice.candidates.length > 1 && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-fg-4">Versions</span>
          {voice.candidates.map((c) => (
            <button
              key={c.n}
              disabled={busy || choose.isPending}
              onClick={() => c.n !== voice.chosen && choose.mutate(c.n)}
              title={c.description}
              className={clsx(
                "rounded-md border px-1.5 py-0.5 font-mono text-[10.5px]",
                c.n === voice.chosen ? "border-amber/40 bg-amber/10 text-amber" : "border-white/[0.08] text-fg-3 hover:text-fg-2",
              )}
            >
              v{c.n}
            </button>
          ))}
        </div>
      )}
      {editing ? (
        <div className="mt-3 flex flex-col gap-2">
          <label className="text-[11px] text-fg-3">
            Voice
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-ink-850 p-2 text-[12px] text-fg outline-none focus:border-amber/40" />
          </label>
          <label className="text-[11px] text-fg-3">
            Reference text (15–30 words)
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} className="mt-1 w-full rounded-lg border border-white/[0.08] bg-ink-850 p-2 text-[12px] text-fg outline-none focus:border-amber/40" />
          </label>
          <div className="flex gap-2">
            <Button size="sm" variant="primary" loading={recast.isPending} disabled={busy} onClick={() => recast.mutate()}>
              Cast this voice
            </Button>
            <Button size="sm" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
          {recast.error && <p className="text-[11.5px] text-bad">{recast.error.message}</p>}
        </div>
      ) : (
        <Button size="sm" className="mt-3" icon={<RotateCcw className="size-3.5" />} disabled={busy} onClick={() => setEditing(true)}>
          Recast
        </Button>
      )}
    </div>
  );
}

function PlayButton({ src }: { src: string }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  return (
    <>
      <audio ref={audio} src={src} preload="none" onEnded={() => setPlaying(false)} onPause={() => setPlaying(false)} onPlay={() => setPlaying(true)} />
      <button
        onClick={() => (playing ? audio.current?.pause() : void audio.current?.play())}
        aria-label={playing ? "Pause" : "Play"}
        className="flex size-10 shrink-0 items-center justify-center rounded-full border border-engine-qwen/30 bg-engine-qwen/10 text-engine-qwen hover:bg-engine-qwen/20"
      >
        {playing ? <Pause className="size-4" /> : <Play className="size-4 translate-x-[1px]" />}
      </button>
    </>
  );
}

export function VoiceClips({ p, compact }: { p: Production; compact?: boolean }) {
  const v = p.preprod?.voice;
  if (!v) return null;
  return (
    <div className={clsx("grid gap-3", compact ? "mt-4 md:grid-cols-3" : "mt-1 md:grid-cols-2 xl:grid-cols-3")}>
      {v.clips.map((c) => (
        <div key={c.shot} className="overflow-hidden rounded-xl border border-white/[0.06] bg-ink-900">
          <video src={mediaUrl(c.video)} poster={thumbUrl(c.video, 0.5, 640)} controls preload="metadata" className="aspect-[3/2] w-full bg-black object-cover" />
          <div className="p-3">
            <p className="text-[12px] text-fg">“{c.line}”</p>
            <p className="mt-1 text-[11px] text-fg-4">
              Heard: “{c.heard}” · {c.wer <= 0.2 ? "words ✓" : `WER ${Math.round(c.wer * 100)}%`} · {duration(c.render_s)}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

export function Conversation({ p }: { p: Production }) {
  const said = p.preprod?.conversation ?? [];
  if (!said.length) return <p className="text-[12.5px] text-fg-3">No agent messages yet.</p>;
  return (
    <ol className="flex flex-col gap-3">
      {said.map((e, i) => (
        <li key={i} className="flex gap-3">
          <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full border border-engine-claude/30 bg-engine-claude/10 text-engine-claude">
            <Bot className="size-3.5" />
          </span>
          <div className="min-w-0">
            <div className="flex items-baseline gap-2 text-[12px]">
              <span className="font-medium text-fg">{String(e.agent ?? e.type)}</span>
              <span className="font-mono text-[10.5px] text-fg-4">{new Date(e.t * 1000).toLocaleTimeString()}</span>
              {e.type === "run_failed" && <StatusPill status="failed" />}
            </div>
            <p className="mt-0.5 text-[12.5px] leading-relaxed whitespace-pre-wrap text-fg-2">{String(e.text ?? e.error ?? e.summary ?? "")}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}
