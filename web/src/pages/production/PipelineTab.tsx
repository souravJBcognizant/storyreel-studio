import { Anchor, Clapperboard, Flag, Hourglass, Link2, Plug, Sparkles } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { ShotGraph } from "../../components/pipeline/ShotGraph";
import { StageDetail, StageRail } from "../../components/pipeline/StageRail";
import { Button, EngineTag, ProgressBar, SectionTitle, Stat } from "../../components/ui";
import { thumbUrl, type Production, type Stage } from "../../lib/api";
import { CastPanel, KeyframesPanel, NextStep, SheetsPanel, VoiceClips, VoicesPanel } from "./Preproduction";
import { clock, duration, pct } from "../../lib/format";

export function PipelineTab({ p, onOpenShot, onRender }: { p: Production; onOpenShot: (id: string) => void; onRender: () => void }) {
  const focus =
    p.stages.find((s) => ["running", "queued", "awaiting_approval", "failed"].includes(s.status)) ??
    p.stages.find((s) => s.status === "pending") ??
    p.stages[p.stages.length - 1];
  const [params] = useSearchParams();
  const [selected, setSelected] = useState<string | null>(() => params.get("stage")); // deep link: ?tab=pipeline&stage=voice
  const stage = p.stages.find((s) => s.key === (selected ?? focus.key))!;

  return (
    <div className="flex flex-col gap-7">
      <NextStep p={p} />
      {p.active_job?.kind === "render" && <LiveRender p={p} />}

      <section className="card p-5 pb-3">
        <SectionTitle eyebrow="Pipeline" title="From story to film" right={<Legend />} />
        <StageRail stages={p.stages} selected={stage.key} onSelect={setSelected} />
      </section>

      <StageDetail stage={stage}>
        <StageContext p={p} stage={stage} onRender={onRender} />
      </StageDetail>

      <section>
        <SectionTitle
          eyebrow="Render graph"
          title="Shots and how they connect"
          right={
            <div className="flex flex-wrap items-center gap-4 text-[11.5px] text-fg-3">
              <span className="flex items-center gap-1">
                <Sparkles className="size-3" /> new
              </span>
              <span className="flex items-center gap-1">
                <Link2 className="size-3" /> continues
              </span>
              <span className="flex items-center gap-1">
                <Anchor className="size-3" /> anchored
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-[2px] w-5 rounded bg-amber" /> continues from last frame
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-0 w-5 border-t-2 border-dashed border-engine-ltx" /> anchored on a reference
              </span>
            </div>
          }
        />
        {p.scenes.length ? (
          <ShotGraph production={p} onOpen={onOpenShot} />
        ) : (
          <div className="card flex h-[220px] flex-col items-center justify-center gap-2 text-center">
            <Clapperboard className="size-6 text-fg-4" strokeWidth={1.4} />
            <p className="text-[13px] text-fg-2">The shot graph appears once the plan exists.</p>
            <p className="text-[12px] text-fg-4">Each scene becomes a lane; every shot shows its takes and checks live while it renders.</p>
          </div>
        )}
      </section>
    </div>
  );
}

function LiveRender({ p }: { p: Production }) {
  const prog = p.progress;
  const queued = p.active_job?.status === "queued";
  return (
    <section className="card animate-rise relative overflow-hidden border-amber/25 p-5">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(600px_200px_at_0%_0%,rgb(243_169_60/0.10),transparent)]" />
      <div className="relative flex flex-wrap items-start gap-6">
        <div className="min-w-[240px] flex-1">
          <div className="eyebrow flex items-center gap-2 text-amber">
            <span className="size-1.5 animate-pulse-soft rounded-full bg-amber" /> {queued ? "Queued" : "Rendering now"}
          </div>
          <div className="mt-1.5 font-display text-[22px] text-fg">
            {queued
              ? "Waiting for the render engine"
              : prog?.current_shot
                ? `Shot ${prog.current_shot} · take ${(prog.current_take ?? 0) + 1}`
                : prog?.phase === "assembling"
                  ? "Cutting the film together"
                  : "Loading models and checkers"}
          </div>
          <ProgressBar value={prog ? pct(prog.shots_done, prog.shots_total) : 0} live className="mt-4 max-w-xl" />
        </div>
        <div className="grid grid-cols-4 gap-6">
          <Stat label="Shots" value={prog ? `${prog.shots_done}/${prog.shots_total}` : "—"} />
          <Stat label="Takes" value={prog?.takes_done ?? "—"} hint={prog ? `${prog.renders_done} rendered` : undefined} />
          <Stat label="LTX time" value={prog ? duration(prog.render_s_total) : "—"} />
          <Stat label="Left" value={prog?.eta_s ? `≈ ${duration(prog.eta_s)}` : "—"} hint="estimate" />
        </div>
      </div>
    </section>
  );
}

function StageContext({ p, stage, onRender }: { p: Production; stage: Stage; onRender: () => void }) {
  const shots = p.scenes.flatMap((s) => s.shots);
  const takes = shots.flatMap((s) => s.takes);
  const firstPass = shots.filter((s) => s.takes[0]?.passed).length;
  switch (stage.key) {
    case "story":
      return (
        <div className="flex gap-4">
          {p.first_frame && <img src={thumbUrl(p.first_frame, 0, 360)} alt="" className="h-24 w-36 shrink-0 rounded-lg object-cover ring-1 ring-white/10" />}
          <p className="line-clamp-5 text-[13px] leading-relaxed text-fg-2">{p.story}</p>
        </div>
      );
    case "plan":
      return stage.status === "done" || stage.status === "awaiting_approval" ? (
        <p>
          {p.scenes.length} scenes, {shots.length} shots, {shots.filter((s) => s.line).length} spoken lines. See the Plan tab for the screenplay.
        </p>
      ) : (
        <Waiting p={p} />
      );
    case "render":
      return stage.status === "done" || takes.length ? (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <span>
            {takes.length} takes for {shots.length} shots · {firstPass}/{shots.length} passed first time ·{" "}
            {duration(takes.filter((t) => !t.cached).reduce((a, t) => a + t.render_s, 0))} of LTX rendering
          </span>
          {!p.active_job && p.can_render && (
            <Button size="sm" onClick={onRender}>
              Re-render (uses the cache)
            </Button>
          )}
        </div>
      ) : p.can_render ? (
        <Button size="sm" variant="primary" onClick={onRender}>
          Render film
        </Button>
      ) : (
        <p className="text-fg-3">Starts once the plan, keyframes and voice are approved.</p>
      );
    case "analysis":
      return p.preprod?.cast ? <CastPanel p={p} /> : stage.status === "skipped" ? <Skipped /> : <Waiting p={p} />;
    case "sheets":
      return p.preprod?.keyframes ? <SheetsPanel p={p} /> : stage.status === "skipped" ? <Skipped /> : <Waiting p={p} />;
    case "keyframes":
      return p.preprod?.keyframes && Object.keys(p.preprod.keyframes.scenes).length ? (
        <KeyframesPanel p={p} />
      ) : stage.status === "skipped" ? (
        <Skipped />
      ) : (
        <Waiting p={p} />
      );
    case "voice":
      if (p.preprod?.voices) return <VoicesPanel p={p} />;
      if (p.preprod?.voice) return <VoiceClips p={p} />;
      return stage.status === "done" ? (
        <p>
          Voice locked: {p.characters.map((c) => `${c.id} — “${c.voice_phrase}”, ${c.voice_refs} approved reference takes`).join("; ")}.
        </p>
      ) : (
        <Waiting p={p} />
      );
    case "assemble":
    case "film":
      return p.film ? (
        <p>
          {clock(p.film.duration)} film, {p.film.markers.length} shots, faded at scene changes and loudness-normalized.
        </p>
      ) : (
        <p className="flex items-center gap-2 text-fg-3">
          <Hourglass className="size-3.5" /> After the render.
        </p>
      );
    default:
      return stage.status === "skipped" ? <Skipped /> : <Waiting p={p} />;
  }
}

function Skipped() {
  return <p className="text-fg-3">Not used for this production — it started from a hand-written plan.</p>;
}

function Waiting({ p }: { p: Production }) {
  return (
    <p className="flex items-start gap-2 rounded-lg border border-white/[0.06] bg-ink-900/60 px-3 py-2.5 text-[12.5px] text-fg-3">
      <Plug className="mt-0.5 size-3.5 shrink-0 text-engine-claude" />
      {p.active_job?.kind === "preprod"
        ? "The agents are on it — this fills in as soon as they save their work."
        : p.can_plan
          ? "Runs when you start “Plan with agents”, and pauses here for your approval where the flag is shown."
          : "Not produced for this film."}
    </p>
  );
}

function Legend() {
  return (
    <div className="hidden items-center gap-4 lg:flex">
      {(["claude", "openai", "ltx", "qwen", "ffmpeg"] as const).map((e) => (
        <EngineTag key={e} engine={e} />
      ))}
      <span className="flex items-center gap-1 text-[11px] text-fg-3">
        <Flag className="size-3 text-warn" /> your approval
      </span>
    </div>
  );
}
