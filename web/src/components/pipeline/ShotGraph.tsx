import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import clsx from "clsx";
import { Anchor, ImageIcon, Link2, Mic2, Sparkles } from "lucide-react";
import { useMemo } from "react";
import type { Production, Scene, Shot } from "../../lib/api";
import { thumbUrl } from "../../lib/api";
import { ScoreChip, StatusPill } from "../ui";

const W = 212; // shot node
const H = 212;
const GAP = 44;
const PAD = 26;
const HEADER = 50;
const LANE_GAP = 26;
const REF_W = 132;
const REF_H = 112;
const REF_COL = REF_W + 70; // left column for reference frames

type ShotData = { shot: Shot; order: number; onOpen: (id: string) => void };
type SceneData = { scene: Scene; index: number };
type RefData = { image: string; label: string };

export function ShotGraph({ production, onOpen }: { production: Production; onOpen: (shotId: string) => void }) {
  const { nodes, edges } = useMemo(() => layout(production, onOpen), [production, onOpen]);
  if (!production.scenes.length) return null;
  const lanes = production.scenes.length;
  const height = Math.min(Math.max(lanes * 230 + 80, 380), 900);
  return (
    <div className="overflow-hidden rounded-[var(--radius-card)] border border-white/[0.06] bg-ink-900/60" style={{ height }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.06, maxZoom: 1 }}
        minZoom={0.3}
        maxZoom={1.6}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="rgb(255 240 220 / 0.07)" />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
    </div>
  );
}

function layout(production: Production, onOpen: (id: string) => void) {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const refs = new Map<string, { y: number; targets: string[] }>();
  const widest = Math.max(...production.scenes.map((s) => s.shots.length));
  const laneW = widest * (W + GAP) - GAP + PAD * 2;
  const laneH = HEADER + H + PAD;
  const hasRefs = production.scenes.some((s) => s.shots.some((shot) => shot.start === "anchor" && shot.image));
  const x0 = hasRefs ? REF_COL : 0;
  let order = 0;

  production.scenes.forEach((scene, si) => {
    const y = si * (laneH + LANE_GAP);
    nodes.push({
      id: `scene-${scene.id}`,
      type: "scene",
      position: { x: x0, y },
      data: { scene, index: si } satisfies SceneData,
      style: { width: laneW, height: laneH },
      zIndex: -1,
      selectable: false,
    });
    scene.shots.forEach((shot, j) => {
      nodes.push({
        id: shot.id,
        type: "shot",
        position: { x: x0 + PAD + j * (W + GAP), y: y + HEADER },
        data: { shot, order: ++order, onOpen } satisfies ShotData,
      });
      if (shot.start === "continue" && shot.from) {
        const skips = scene.shots.findIndex((s) => s.id === shot.from) !== j - 1;
        edges.push({
          id: `${shot.from}->${shot.id}`,
          source: shot.from,
          target: shot.id,
          type: skips ? "smoothstep" : "default",
          sourceHandle: skips ? "top-out" : "right",
          targetHandle: skips ? "top-in" : "left",
          animated: shot.status === "rendering",
          style: { stroke: "#f3a93c", strokeWidth: 1.8, opacity: 0.9 },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#f3a93c", width: 16, height: 16 },
        });
      }
      if (shot.start === "anchor" && shot.image) {
        const ref = refs.get(shot.image) ?? { y: y + HEADER + (H - REF_H - 30) / 2, targets: [] };
        ref.targets.push(shot.id);
        refs.set(shot.image, ref);
      }
    });
  });

  [...refs.entries()].forEach(([image, ref], i) => {
    const id = `ref-${i}`;
    const character = production.characters.find((c) => c.image === image);
    nodes.push({
      id,
      type: "ref",
      position: { x: 0, y: ref.y },
      data: { image, label: character ? `${character.id} · reference` : "reference frame" } satisfies RefData,
    });
    ref.targets.forEach((t) =>
      edges.push({
        id: `${id}->${t}`,
        source: id,
        target: t,
        targetHandle: "left",
        style: { stroke: "#97a3f2", strokeWidth: 1.6, strokeDasharray: "5 5" },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#97a3f2", width: 16, height: 16 },
      }),
    );
  });
  return { nodes, edges };
}

const START_ICON = { fresh: Sparkles, continue: Link2, anchor: Anchor } as const;
const START_LABEL = { fresh: "new shot", continue: "continues", anchor: "anchored" } as const;

function ShotNode({ data }: NodeProps<Node<ShotData>>) {
  const { shot, order, onOpen } = data;
  const chosen = shot.chosen != null ? shot.takes[shot.chosen] : null;
  const preview = chosen ?? shot.takes[shot.takes.length - 1];
  const StartIcon = START_ICON[shot.start];
  const planned = Math.max(shot.takes_planned, shot.takes.length + (shot.status === "rendering" ? 1 : 0));
  return (
    <button
      onClick={() => onOpen(shot.id)}
      className={clsx(
        "group relative flex w-[212px] flex-col justify-start overflow-hidden rounded-xl border bg-ink-800 text-left shadow-[var(--shadow-card)] transition-all hover:-translate-y-0.5 hover:border-white/20",
        shot.status === "rendering" || shot.status === "checking"
          ? "border-amber/50 ring-4 ring-amber/10"
          : shot.status === "needs_review"
            ? "border-warn/40"
            : "border-white/[0.08]",
      )}
      style={{ height: H }}
    >
      <Handle type="target" position={Position.Left} id="left" className="!size-0 !border-0 !bg-transparent" />
      <Handle type="source" position={Position.Right} id="right" className="!size-0 !border-0 !bg-transparent" />
      <Handle type="target" position={Position.Top} id="top-in" className="!size-0 !border-0 !bg-transparent" />
      <Handle type="source" position={Position.Top} id="top-out" className="!size-0 !border-0 !bg-transparent" />
      <div className="relative aspect-[3/2] w-full overflow-hidden bg-ink-900" style={{ height: 112 }}>
        {preview ? (
          <img
            src={thumbUrl(preview.path, 1.2, 420)}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]"
          />
        ) : (
          <div className={clsx("h-full w-full", shot.status === "rendering" ? "skeleton rounded-none" : "bg-ink-850")} />
        )}
        <div className="absolute inset-x-0 top-0 flex items-center justify-between p-2">
          <span className="rounded-md bg-black/60 px-1.5 py-0.5 font-mono text-[10.5px] text-white/90 backdrop-blur">
            {String(order).padStart(2, "0")} · {shot.id}
          </span>
          <span className="inline-flex items-center gap-1 rounded-md bg-black/60 px-1.5 py-0.5 text-[10px] text-white/80 backdrop-blur">
            <StartIcon className="size-3" /> {START_LABEL[shot.start]}
          </span>
        </div>
        {chosen && (
          <span className="absolute right-2 bottom-2 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[10px] text-white/85 backdrop-blur">
            {chosen.seconds.toFixed(1)}s
          </span>
        )}
      </div>
      <div className="flex flex-col gap-1.5 px-2.5 pt-2">
        <div className="flex items-center justify-between gap-2">
          <StatusPill status={shot.status} />
          <TakeDots shot={shot} planned={planned} />
        </div>
        <div className="flex min-h-[20px] items-center gap-1">
          {shot.line ? (
            <>
              <Mic2 className="size-3 shrink-0 text-fg-3" />
              <span className="truncate text-[11px] text-fg-2 italic">“{shot.line}”</span>
            </>
          ) : (
            <span className="truncate text-[11px] text-fg-3">{shot.action}</span>
          )}
        </div>
        <div className="flex min-h-[22px] items-center gap-1">
          {chosen?.voice != null && <ScoreChip metric="voice" value={chosen.voice} />}
          {chosen?.identity != null && <ScoreChip metric="identity" value={chosen.identity} />}
          {chosen && chosen.voice == null && chosen.identity == null && (
            <span className="text-[10.5px] text-fg-4">{shot.identity_check ? "—" : "no character checks"}</span>
          )}
        </div>
      </div>
    </button>
  );
}

function TakeDots({ shot, planned }: { shot: Shot; planned: number }) {
  return (
    <span className="flex items-center gap-1" title={`${shot.takes.length} take(s)`}>
      {Array.from({ length: planned }, (_, i) => {
        const t = shot.takes[i];
        const live = !t && shot.status === "rendering" && shot.current_take === i;
        return (
          <span
            key={i}
            className={clsx(
              "size-2 rounded-full",
              t && t.passed && (i === shot.chosen ? "bg-ok ring-2 ring-ok/30" : "bg-ok/60"),
              t && !t.passed && "bg-bad/80",
              live && "animate-pulse-soft bg-amber",
              !t && !live && "border border-white/20",
            )}
          />
        );
      })}
    </span>
  );
}

function SceneNode({ data }: NodeProps<Node<SceneData>>) {
  const { scene, index } = data;
  return (
    <div className="h-full w-full rounded-2xl border border-white/[0.06] bg-white/[0.018]">
      <div className="flex items-baseline gap-2 px-[26px] pt-3.5">
        <span className="font-mono text-[10.5px] text-fg-4">SCENE {index + 1}</span>
        <span className="font-display text-[15px] text-fg capitalize">{scene.id}</span>
        <span className="truncate text-[11px] text-fg-3">{scene.setting}</span>
      </div>
    </div>
  );
}

function RefNode({ data }: NodeProps<Node<RefData>>) {
  return (
    <div className="w-[132px] overflow-hidden rounded-xl border border-engine-ltx/40 bg-ink-800 shadow-[var(--shadow-card)]">
      <Handle type="source" position={Position.Right} className="!size-0 !border-0 !bg-transparent" />
      <img src={thumbUrl(data.image, 0, 300)} alt="" className="aspect-[3/2] w-full object-cover" />
      <div className="flex items-center gap-1.5 px-2 py-1.5 text-[10.5px] text-fg-2">
        <ImageIcon className="size-3 text-engine-ltx" /> {data.label}
      </div>
    </div>
  );
}

const NODE_TYPES = { shot: ShotNode, scene: SceneNode, ref: RefNode };
