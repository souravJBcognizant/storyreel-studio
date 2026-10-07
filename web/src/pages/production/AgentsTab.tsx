import { useQuery } from "@tanstack/react-query";
import { Background, BackgroundVariant, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import clsx from "clsx";
import { ArrowRight, Bot, Check, ChevronDown, Crown, Image as ImageIcon, Loader2, Wrench, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { EmptyState, ENGINE, Stat } from "../../components/ui";
import { api, mediaUrl, thumbUrl, type AgentNetwork, type PipelineEvent, type Production } from "../../lib/api";
import { duration, stamp } from "../../lib/format";

// ---------------------------------------------------------------- trace → state

type AgentStatus = "idle" | "working" | "done" | "error";
interface ToolCall {
  id: number;
  caller: string;
  tool: string;
  params: string;
  output?: string;
  images?: { path: string; score?: number }[];
  ok?: boolean;
  start: number;
  end?: number;
}
interface Delegation {
  id: number;
  from: string;
  to: string;
  request: string;
  result?: string;
  start: number;
  end?: number;
}
type Moment =
  | { kind: "delegation"; t: number; d: Delegation }
  | { kind: "tool"; t: number; c: ToolCall }
  | { kind: "answer"; t: number; agent: string; text: string; final?: boolean }
  | { kind: "status"; t: number; text: string; bad?: boolean };

interface TraceState {
  agents: Record<string, { status: AgentStatus; start?: number; end?: number; tool?: string; toolSince?: number; calls: Record<string, number> }>;
  calls: ToolCall[];
  delegations: Delegation[];
  moments: Moment[];
  cost: number | null;
  started: number | null;
  ended: number | null;
  failed: string | null;
}

function reduce(trace: PipelineEvent[], network: AgentNetwork): TraceState {
  const s: TraceState = { agents: {}, calls: [], delegations: [], moments: [], cost: null, started: null, ended: null, failed: null };
  for (const a of network.agents) s.agents[a.name] = { status: "idle", calls: {} };
  const agent = (name?: unknown) => (typeof name === "string" && s.agents[name] ? s.agents[name] : null);
  let n = 0;
  for (const e of trace) {
    if (e.type === "run_started") s.started = e.t;
    if (e.type === "run_finished") {
      s.ended = e.t;
      s.moments.push({ kind: "status", t: e.t, text: "Pre-production finished" });
    }
    if (e.type === "run_failed") {
      s.ended = e.t;
      s.failed = String(e.error);
      s.moments.push({ kind: "status", t: e.t, text: `Run failed: ${String(e.error)}`, bad: true });
    }
    if (e.type !== "trace") continue;
    const kind = e.kind as string;
    if (kind === "input") {
      const a = agent(e.agent);
      if (a && a.status !== "working") Object.assign(a, { status: "working", start: a.start ?? e.t });
    } else if (kind === "invoke") {
      const from = String(e.agent ?? "");
      const to = String(e.target ?? "");
      if (s.agents[to]) {
        let request = "";
        try {
          request = JSON.parse(String(e.params)).request ?? String(e.params);
        } catch {
          request = String(e.params);
        }
        const d: Delegation = { id: n++, from, to, request, start: e.t };
        s.delegations.push(d);
        s.moments.push({ kind: "delegation", t: e.t, d });
        Object.assign(s.agents[to], { status: "working", start: s.agents[to].start ?? e.t });
      }
    } else if (kind === "tool_start") {
      const caller = String(e.caller ?? "");
      const c: ToolCall = { id: n++, caller, tool: String(e.agent), params: String(e.params ?? ""), start: e.t };
      s.calls.push(c);
      s.moments.push({ kind: "tool", t: e.t, c });
      const a = agent(caller);
      if (a) Object.assign(a, { status: "working", tool: c.tool, toolSince: e.t, calls: { ...a.calls, [c.tool]: (a.calls[c.tool] ?? 0) + 1 } });
    } else if (kind === "tool_end") {
      const open = [...s.calls].reverse().find((c) => c.tool === e.agent && c.end == null);
      if (open) Object.assign(open, { end: e.t, ok: e.ok as boolean, output: String(e.output ?? ""), images: e.images as ToolCall["images"] });
      const a = agent(e.caller);
      if (a) Object.assign(a, { tool: undefined, toolSince: undefined });
    } else if (kind === "result") {
      const open = [...s.delegations].reverse().find((d) => d.from === e.agent && d.end == null);
      if (open) Object.assign(open, { end: e.t, result: String(e.text ?? "") });
    } else if (kind === "answer") {
      const a = agent(e.agent);
      if (a) Object.assign(a, { status: "done", end: e.t, tool: undefined });
      s.moments.push({ kind: "answer", t: e.t, agent: String(e.agent), text: String(e.text ?? "") });
    } else if (kind === "final") {
      s.moments.push({ kind: "answer", t: e.t, agent: network.front_man, text: String(e.text ?? ""), final: true });
    } else if (kind === "usage" && !String(e.path).includes(".")) {
      s.cost = (e.cost as number) ?? s.cost; // the front man's usage includes everyone below it
    }
  }
  if (s.failed) for (const a of Object.values(s.agents)) if (a.status === "working") a.status = "error";
  return s;
}

/** Runs recorded before live tracing: who is done/working, from the files the agents saved. */
function reduceFromFiles(p: Production, network: AgentNetwork): TraceState {
  const s: TraceState = { agents: {}, calls: [], delegations: [], moments: [], cost: null, started: null, ended: null, failed: null };
  const live = p.active_job?.kind === "preprod";
  const pre = p.preprod;
  const kf = pre?.keyframes;
  const scenes = Object.values(kf?.scenes ?? {});
  const keyframesDone = !!pre?.screenplay && scenes.length === pre.screenplay.scenes.length && scenes.every((sc) => sc.chosen != null);
  const planDone = p.scenes.length > 0;
  const done: Record<string, boolean> = {
    StoryAnalyst: !!pre?.cast,
    Screenwriter: !!pre?.screenplay,
    KeyframeArtist: keyframesDone,
    ShotPlanner: planDone,
  };
  let working = live;
  for (const a of network.agents) {
    if (a.name === network.front_man) {
      s.agents[a.name] = { status: live ? "working" : planDone ? "done" : "idle", calls: {} };
      continue;
    }
    const status: AgentStatus = done[a.name] ? "done" : working ? "working" : "idle";
    if (status === "working") working = false; // only the first unfinished specialist is at work
    s.agents[a.name] = { status, calls: {} };
  }
  let id = 0;
  const tool = (caller: string, name: string, output: Record<string, unknown>) =>
    s.moments.push({ kind: "tool", t: 0, c: { id: id++, caller, tool: name, params: "", output: JSON.stringify(output), ok: true, start: 0, end: 0 } });
  if (pre?.cast) s.moments.push({ kind: "answer", t: 0, agent: "StoryAnalyst", text: `Saved the cast: ${pre.cast.characters.map((c) => c.name).join(", ")}; props: ${Object.keys(pre.cast.props).join(", ") || "none"}.` });
  if (pre?.screenplay) s.moments.push({ kind: "answer", t: 0, agent: "Screenwriter", text: `${pre.screenplay.logline}\n\nScenes: ${pre.screenplay.scenes.map((sc) => sc.id).join(", ")}.` });
  for (const [k, v] of Object.entries(kf?.sheets ?? {})) tool("KeyframeArtist", "MakeCharacterSheet", { sheet: v, character_id: k });
  for (const [k, v] of Object.entries(kf?.props ?? {})) tool("KeyframeArtist", "MakePropSheet", { prop_sheet: v, prop_id: k });
  for (const [sid, sc] of Object.entries(kf?.scenes ?? {}))
    for (const c of sc.candidates) tool("KeyframeArtist", `MakeSceneKeyframe · ${sid} v${c.n}${sc.chosen === c.n ? " (chosen)" : ""}`, { frame: c.frame, review: c.review, advice: c.review.verdict.slice(0, 60) });
  if (pre?.summary) s.moments.push({ kind: "answer", t: 0, agent: network.front_man, text: pre.summary, final: true });
  return s;
}

const parseOutput = (text?: string): Record<string, unknown> | null => {
  if (!text) return null;
  try {
    const v = JSON.parse(text);
    return typeof v === "object" && v ? v : null;
  } catch {
    return null;
  }
};
const IMAGE_KEYS = ["frame", "sheet", "prop_sheet"];

type Made = { path: string; score?: number };

/** The images a tool call made: one (older tools) or a batch (MakeReferenceSheets, MakeKeyframes). */
function imagesOf(out: Record<string, unknown> | null, recorded?: unknown): Made[] {
  if (Array.isArray(recorded)) return recorded as Made[]; // listed by the runner, so long outputs still show them
  if (!out) return [];
  const one = IMAGE_KEYS.map((k) => out[k]).find((v): v is string => typeof v === "string");
  if (one) return [{ path: one, score: (out.review as { score?: number } | undefined)?.score }];
  const made = out.made && typeof out.made === "object" ? Object.values(out.made as Record<string, unknown>) : [];
  const results = Array.isArray(out.results) ? (out.results as { frame?: unknown; review?: { score?: number } }[]) : [];
  return [
    ...made.filter((v): v is string => typeof v === "string").map((path) => ({ path })),
    ...results.filter((r) => typeof r.frame === "string").map((r) => ({ path: r.frame as string, score: r.review?.score })),
  ];
}

/** Every sheet and keyframe candidate saved for the production. */
function imagesSaved(p: Production): number {
  const kf = p.preprod?.keyframes;
  if (!kf) return 0;
  const scenes = Object.values(kf.scenes);
  return (
    Object.keys(kf.sheets).length +
    Object.keys(kf.props).length +
    scenes.reduce((n, sc) => n + sc.candidates.length + Object.values(sc.singles ?? {}).reduce((m, e) => m + e.candidates.length, 0), 0)
  );
}

// ---------------------------------------------------------------- tab

export function AgentsTab({ p }: { p: Production }) {
  const network = useQuery({ queryKey: ["agent-network"], queryFn: api.agentNetwork, staleTime: Infinity });
  const trace = p.preprod?.trace ?? [];
  const live = p.active_job?.kind === "preprod";
  const traced = trace.some((e) => e.type === "trace");
  const state = useMemo(
    () => (network.data ? (traced ? reduce(trace, network.data) : reduceFromFiles(p, network.data)) : null),
    [trace, network.data, traced, p],
  );
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(id);
  }, [live]);

  if (!network.data || !state) return <div className="skeleton h-[520px]" />;
  if (!traced && !p.preprod?.cast && !live)
    return (
      <div className="card">
        <EmptyState icon={<Bot className="size-5" />} title={live ? "The agents are starting…" : "No agent run recorded yet"}>
          {live
            ? "The Director is reading the brief. Its team appears here as soon as it starts delegating."
            : "Start “Plan with agents” to watch the Director's team work here live: who is doing what, every tool call, the images as they are made, and the cost."}
        </EmptyState>
      </div>
    );

  const images = imagesSaved(p);
  const lastEvent = trace.length ? trace[trace.length - 1].t : now;
  const elapsed = (state.ended ?? (live ? now : lastEvent)) - (state.started ?? now);
  return (
    <div className="flex flex-col gap-6">
      <section className="card flex flex-wrap items-center gap-x-10 gap-y-4 px-5 py-4">
        <div className="flex items-center gap-3">
          <span className={clsx("flex size-9 items-center justify-center rounded-xl border", live ? "border-amber/40 bg-amber/10 text-amber" : "border-white/10 bg-ink-800 text-fg-2")}>
            {live ? <Loader2 className="size-4 animate-spin" /> : <Bot className="size-4" />}
          </span>
          <div>
            <div className="text-[13.5px] font-medium text-fg">{live ? "Agents at work" : state.failed ? "Run failed" : "Last run"}</div>
            <div className="text-[11.5px] text-fg-3">storyreel network · neuro-san · {network.data.agents.length} agents, {network.data.tools.length} tools</div>
          </div>
        </div>
        {!traced && (
          <p className="max-w-sm text-[11.5px] leading-relaxed text-fg-3">
            This run started before live tracing was switched on, so it shows what the agents have saved so far. Runs from now on
            show every delegation and tool call as it happens.
          </p>
        )}
        {traced && <Stat label="Elapsed" value={duration(elapsed)} />}
        {traced && <Stat label="Delegations" value={state.delegations.length} />}
        {traced && <Stat label="Tool calls" value={state.calls.length} hint={`${state.calls.filter((c) => c.ok === false).length} failed`} />}
        <Stat label="Images made" value={images} hint={network.data.image_model ?? "OpenAI"} />
        <Stat label="Claude cost" value={state.cost != null ? `$${state.cost.toFixed(2)}` : "—"} hint="from neuro-san's token accounting" />
      </section>

      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <NetworkGraph network={network.data} state={state} live={live} />
        <Feed state={state} live={live} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- graph

type AgentData = { name: string; model: string; tools: string[]; status: AgentStatus; tool?: string; since?: number; calls: Record<string, number>; front: boolean; engines: Record<string, string>; step?: number };

function NetworkGraph({ network, state, live }: { network: AgentNetwork; state: TraceState; live: boolean }) {
  const engines = useMemo(() => Object.fromEntries(network.tools.map((t) => [t.name, t.engine])), [network]);
  const { nodes, edges } = useMemo(() => {
    const specialists = network.agents.filter((a) => a.name !== network.front_man);
    const W = 248;
    const GAP = 28;
    // Specialists in two rows, in delegation order: the first half above the Director, the rest below.
    const perRow = Math.ceil(specialists.length / 2);
    const rowWidth = (n: number) => n * W + Math.max(0, n - 1) * GAP;
    const total = rowWidth(perRow);
    const front = network.agents.find((a) => a.name === network.front_man)!;
    const mk = (a: (typeof network.agents)[number], x: number, y: number, isFront: boolean, step?: number): Node => {
      const st = state.agents[a.name];
      return {
        id: a.name,
        type: "agent",
        position: { x, y },
        data: { name: a.name, model: a.model, tools: isFront ? [] : a.tools, status: st.status, tool: st.tool, since: st.toolSince, calls: st.calls, front: isFront, engines, step } satisfies AgentData,
      };
    };
    // Hub and spokes: the Director sits between the two rows, so no delegation edge runs behind a node.
    const ROW1 = 0;
    const HUB = 250;
    const ROW2 = 380;
    const ns: Node[] = [mk(front, total / 2 - 150, HUB, true)];
    const es: Edge[] = [];
    specialists.forEach((a, i) => {
      const above = i < perRow;
      const inRow = above ? perRow : specialists.length - perRow;
      const col = above ? i : i - perRow;
      const x = (total - rowWidth(inRow)) / 2 + col * (W + GAP); // each row centred under the widest
      ns.push(mk(a, x, above ? ROW1 : ROW2, false, i + 1));
      const open = state.delegations.some((d) => d.to === a.name && d.end == null);
      const done = state.agents[a.name].status === "done";
      es.push({
        id: `${front.name}-${a.name}`,
        source: front.name,
        target: a.name,
        sourceHandle: above ? "out-top" : "out-bottom",
        targetHandle: above ? "in-bottom" : "in-top",
        animated: open && live,
        style: { stroke: open ? "#f3a93c" : done ? "#5bc98a" : "rgb(255 240 220 / 0.14)", strokeWidth: open ? 2.2 : 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, color: open ? "#f3a93c" : done ? "#5bc98a" : "rgb(255 240 220 / 0.25)", width: 14, height: 14 },
      });
    });
    return { nodes: ns, edges: es };
  }, [network, state, live, engines]);
  return (
    <div className="h-[560px] overflow-hidden rounded-[var(--radius-card)] border border-white/[0.06] bg-ink-900/60">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.08, maxZoom: 1 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
        minZoom={0.4}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="rgb(255 240 220 / 0.07)" />
      </ReactFlow>
    </div>
  );
}

function AgentNode({ data }: NodeProps<Node<AgentData>>) {
  const { name, model, tools, status, tool, since, calls, front, engines, step } = data;
  const tier = model.includes("opus") ? "Opus" : model.includes("sonnet") ? "Sonnet" : model;
  return (
    <div
      className={clsx(
        "rounded-2xl border bg-ink-800 p-3.5 shadow-[var(--shadow-card)] transition-all",
        front ? "w-[300px]" : "w-[248px]",
        status === "working" && "border-amber/60 ring-4 ring-amber/10",
        status === "done" && "border-ok/35",
        status === "error" && "border-bad/50",
        status === "idle" && "border-white/[0.08] opacity-70",
      )}
    >
      <Handle type="target" id="in-top" position={Position.Top} className="!size-0 !border-0 !bg-transparent" />
      <Handle type="target" id="in-bottom" position={Position.Bottom} className="!size-0 !border-0 !bg-transparent" />
      <Handle type="source" id="out-top" position={Position.Top} className="!size-0 !border-0 !bg-transparent" />
      <Handle type="source" id="out-bottom" position={Position.Bottom} className="!size-0 !border-0 !bg-transparent" />
      <div className="flex items-center gap-2.5">
        <span
          className={clsx(
            "flex size-8 shrink-0 items-center justify-center rounded-xl",
            status === "working" ? "bg-amber/15 text-amber" : status === "done" ? "bg-ok/12 text-ok" : status === "error" ? "bg-bad/12 text-bad" : "bg-white/[0.05] text-fg-3",
          )}
        >
          {front ? <Crown className="size-4" /> : status === "working" ? <Loader2 className="size-4 animate-spin" /> : status === "done" ? <Check className="size-4" /> : <Bot className="size-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13.5px] font-semibold text-fg">
            {step && <span className="mr-1.5 font-mono text-[11px] font-normal text-fg-4">{step}</span>}
            {name}
          </div>
          <div className="flex items-center gap-1.5 text-[10.5px]">
            <span className="size-1.5 rounded-[2px]" style={{ background: ENGINE.claude.color }} />
            <span className="text-engine-claude">Claude {tier}</span>
            <span className="font-mono text-fg-4">{status === "idle" ? "waiting" : status}</span>
          </div>
        </div>
      </div>
      {tool && (
        <div className="mt-2.5 flex items-center gap-1.5 rounded-lg border border-amber/25 bg-amber/[0.06] px-2 py-1.5 text-[11px] text-amber">
          <Wrench className="size-3" /> <span className="truncate font-medium">{tool}</span>
          {since && <Elapsed since={since} />}
        </div>
      )}
      {tools.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1">
          {tools.map((t) => {
            const engine = (engines[t] ?? "local") as keyof typeof ENGINE | "local";
            const color = engine === "local" ? "rgb(255 240 220 / 0.35)" : ENGINE[engine as keyof typeof ENGINE].color;
            return (
              <span
                key={t}
                className={clsx(
                  "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px]",
                  t === tool ? "border-amber/50 bg-amber/10 text-amber" : calls[t] ? "border-white/[0.1] text-fg-2" : "border-white/[0.05] text-fg-4",
                )}
                title={engine === "local" ? "runs locally" : `runs on ${ENGINE[engine as keyof typeof ENGINE].label}`}
              >
                <span className="size-1 rounded-full" style={{ background: color }} />
                {t}
                {calls[t] ? <span className="font-mono text-fg-3">×{calls[t]}</span> : null}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(id);
  }, []);
  return <span className="ml-auto font-mono text-[10px] text-amber/80">{Math.max(0, Math.round(now - since))}s</span>;
}

const NODE_TYPES = { agent: AgentNode };

// ---------------------------------------------------------------- feed

type Filter = "all" | "agents" | "tools" | "problems";

function Feed({ state, live }: { state: TraceState; live: boolean }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [follow, setFollow] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  const moments = state.moments.filter((m) =>
    filter === "all"
      ? true
      : filter === "agents"
        ? m.kind === "delegation" || m.kind === "answer"
        : filter === "tools"
          ? m.kind === "tool"
          : (m.kind === "tool" && m.c.ok === false) || (m.kind === "status" && m.bad),
  );
  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [moments.length, follow]);
  return (
    <section className="card flex max-h-[760px] min-h-[560px] flex-col overflow-hidden">
      <div className="flex items-center gap-1.5 border-b border-white/[0.06] px-3 py-2">
        {(["all", "agents", "tools", "problems"] as Filter[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={clsx("h-7 rounded-md px-2.5 text-[12px] capitalize", filter === f ? "bg-white/[0.07] text-fg" : "text-fg-3 hover:text-fg")}
          >
            {f}
          </button>
        ))}
        <label className="ml-auto flex items-center gap-1.5 text-[11.5px] text-fg-3">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} className="accent-amber" /> follow{live ? " live" : ""}
        </label>
      </div>
      <div ref={box} className="flex-1 overflow-y-auto px-4 py-3">
        <ol className="flex flex-col gap-2.5">
          {moments.map((m, i) => (
            <li key={i} className="animate-rise">
              <MomentRow m={m} />
            </li>
          ))}
        </ol>
        {!moments.length && <p className="py-6 text-center text-[12.5px] text-fg-4">Nothing here yet.</p>}
      </div>
    </section>
  );
}

function MomentRow({ m }: { m: Moment }) {
  if (m.kind === "delegation")
    return (
      <Row t={m.t} icon={<ArrowRight className="size-3.5" />} tone="amber">
        <div className="text-[12.5px] text-fg">
          <b className="font-semibold">{m.d.from}</b> <span className="text-fg-3">asks</span> <b className="font-semibold">{m.d.to}</b>
          {m.d.end && <span className="ml-2 font-mono text-[10.5px] text-fg-4">{duration(m.d.end - m.d.start)}</span>}
        </div>
        {m.d.request && <p className="mt-1 line-clamp-3 text-[12px] leading-relaxed text-fg-3">{m.d.request}</p>}
      </Row>
    );
  if (m.kind === "tool") {
    const out = parseOutput(m.c.output);
    const made = imagesOf(out, m.c.images);
    const image = made.length === 1 ? made[0].path : undefined;
    const errors = (out?.errors as unknown[] | undefined) ?? (out?.error ? [out.error] : []);
    return (
      <Row t={m.t} icon={m.c.end == null ? <Loader2 className="size-3.5 animate-spin" /> : m.c.ok === false || errors.length ? <X className="size-3.5" /> : <Wrench className="size-3.5" />} tone={m.c.end == null ? "amber" : errors.length ? "bad" : "dim"}>
        <div className="flex flex-wrap items-baseline gap-x-2 text-[12.5px]">
          <span className="text-fg-3">{m.c.caller}</span>
          <span className="font-mono text-[12px] text-fg">{m.c.tool}</span>
          {m.t > 0 && <span className="font-mono text-[10.5px] text-fg-4">{m.c.end ? duration(m.c.end - m.c.start) : "running…"}</span>}
        </div>
        {errors.length > 0 && (
          <ul className="mt-1 text-[11.5px] text-bad">
            {errors.slice(0, 4).map((er, i) => (
              <li key={i}>• {typeof er === "string" ? er : JSON.stringify(er)}</li>
            ))}
          </ul>
        )}
        {image && (
          <a href={mediaUrl(image)} target="_blank" rel="noreferrer" className="mt-2 block w-[220px] overflow-hidden rounded-lg border border-white/[0.08]">
            <img src={thumbUrl(image, 0, 440)} alt="" className="aspect-[3/2] w-full object-cover" />
            {out?.review != null && typeof out.review === "object" && (
              <div className="flex items-center gap-1.5 bg-ink-850 px-2 py-1 text-[10.5px] text-fg-3">
                <ImageIcon className="size-3" /> review {(out.review as { score: number }).score}/10 · {String(out.advice ?? "")}
              </div>
            )}
          </a>
        )}
        {made.length > 1 && (
          <div className="mt-2 grid max-w-[480px] grid-cols-4 gap-1.5">
            {made.slice(0, 12).map((im) => (
              <a key={im.path} href={mediaUrl(im.path)} target="_blank" rel="noreferrer" className="relative block overflow-hidden rounded-md border border-white/[0.08]">
                <img src={thumbUrl(im.path, 0, 240)} alt="" loading="lazy" className="aspect-[3/2] w-full object-cover" />
                {im.score != null && <span className="absolute right-1 bottom-1 rounded bg-black/60 px-1 font-mono text-[9.5px] text-white/85">{im.score}/10</span>}
              </a>
            ))}
          </div>
        )}
        <Details label="input" text={m.c.params} />
        {m.c.output && !made.length && <Details label="output" text={m.c.output} />}
      </Row>
    );
  }
  if (m.kind === "answer")
    return (
      <Row t={m.t} icon={m.final ? <Crown className="size-3.5" /> : <Bot className="size-3.5" />} tone={m.final ? "ok" : "claude"}>
        <div className="text-[12.5px] font-semibold text-fg">
          {m.agent} {m.final ? <span className="font-normal text-ok">· final summary</span> : <span className="font-normal text-fg-3">· answered</span>}
        </div>
        <Collapsible text={m.text} open={m.final} />
      </Row>
    );
  return (
    <Row t={m.t} icon={m.bad ? <X className="size-3.5" /> : <Check className="size-3.5" />} tone={m.bad ? "bad" : "ok"}>
      <div className={clsx("text-[12.5px]", m.bad ? "text-bad" : "text-ok")}>{m.text}</div>
    </Row>
  );
}

function Row({ t, icon, tone, children }: { t: number; icon: ReactNode; tone: "amber" | "bad" | "dim" | "ok" | "claude"; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <span
        className={clsx(
          "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border",
          tone === "amber" && "border-amber/40 bg-amber/10 text-amber",
          tone === "bad" && "border-bad/40 bg-bad/10 text-bad",
          tone === "dim" && "border-white/10 bg-ink-800 text-fg-3",
          tone === "ok" && "border-ok/40 bg-ok/10 text-ok",
          tone === "claude" && "border-engine-claude/40 bg-engine-claude/10 text-engine-claude",
        )}
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        {children}
        {t > 0 && <div className="mt-0.5 font-mono text-[10px] text-fg-4">{stamp(t)}</div>}
      </div>
    </div>
  );
}

function Collapsible({ text, open }: { text: string; open?: boolean }) {
  const [show, setShow] = useState(!!open);
  const long = text.length > 280;
  return (
    <div className="mt-1">
      <p className={clsx("text-[12px] leading-relaxed whitespace-pre-wrap text-fg-2", !show && long && "line-clamp-4")}>{text}</p>
      {long && (
        <button onClick={() => setShow(!show)} className="mt-1 inline-flex items-center gap-1 text-[11px] text-fg-3 hover:text-fg">
          <ChevronDown className={clsx("size-3 transition-transform", show && "rotate-180")} /> {show ? "less" : "more"}
        </button>
      )}
    </div>
  );
}

function Details({ label, text }: { label: string; text: string }) {
  if (!text || text === "{}") return null;
  let pretty = text;
  try {
    pretty = JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    /* keep as is */
  }
  return (
    <details className="group mt-1">
      <summary className="cursor-pointer list-none text-[11px] text-fg-4 select-none hover:text-fg-2">
        <span className="group-open:hidden">▸</span>
        <span className="hidden group-open:inline">▾</span> {label}
      </summary>
      <pre className="mt-1 max-h-60 overflow-auto rounded-md border border-white/[0.06] bg-ink-950/60 p-2 font-mono text-[10.5px] leading-relaxed whitespace-pre-wrap text-fg-3">{pretty}</pre>
    </details>
  );
}
