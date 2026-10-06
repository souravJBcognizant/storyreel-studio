import clsx from "clsx";
import { Maximize2, Minimize2, Pause, Play, Rewind, Volume2, VolumeX } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import type { FilmMarker } from "../lib/api";
import { clock } from "../lib/format";

const FRAME = 1 / 24;
const RATES = [0.5, 1, 1.5, 2];
const SCENE_TINTS = ["#f3a93c", "#97a3f2", "#6fcaa3", "#e3895f", "#cdb57b"];

export function VideoPlayer({
  src,
  poster,
  markers = [],
  autoPlay = false,
  className,
  onShotChange,
  seek: seekRequest,
}: {
  src: string;
  poster?: string;
  markers?: FilmMarker[];
  autoPlay?: boolean;
  className?: string;
  onShotChange?: (shot: string | null) => void;
  /** Change `n` to jump to `t` seconds (e.g. from a chapter list). */
  seek?: { t: number; n: number };
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [length, setLength] = useState(0);
  const [buffered, setBuffered] = useState(0);
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [rate, setRate] = useState(1);
  const [hover, setHover] = useState<number | null>(null);
  const [idle, setIdle] = useState(false);
  const [full, setFull] = useState(false);
  const [scrubbing, setScrubbing] = useState(false);
  const idleTimer = useRef<number | undefined>(undefined);

  const sceneTint = useMemo(() => {
    const scenes = [...new Set(markers.map((m) => m.scene))];
    return (scene: string) => SCENE_TINTS[scenes.indexOf(scene) % SCENE_TINTS.length];
  }, [markers]);
  const current = markers.find((m) => time >= m.start && time < m.end) ?? null;

  useEffect(() => onShotChange?.(current?.shot ?? null), [current?.shot, onShotChange]);

  useEffect(() => {
    if (!seekRequest || !video.current) return;
    video.current.currentTime = seekRequest.t;
    setTime(seekRequest.t);
    void video.current.play();
  }, [seekRequest?.n]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onFs = () => setFull(document.fullscreenElement === wrap.current);
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  const poke = useCallback(() => {
    setIdle(false);
    window.clearTimeout(idleTimer.current);
    idleTimer.current = window.setTimeout(() => setIdle(true), 2600);
  }, []);

  const toggle = useCallback(() => {
    const v = video.current;
    if (!v) return;
    if (v.paused) void v.play();
    else v.pause();
  }, []);

  const seek = useCallback((t: number) => {
    const v = video.current;
    if (!v || !Number.isFinite(v.duration)) return;
    v.currentTime = Math.min(Math.max(t, 0), v.duration);
    setTime(v.currentTime);
  }, []);

  const fraction = (clientX: number) => {
    const r = track.current?.getBoundingClientRect();
    if (!r) return 0;
    return Math.min(Math.max((clientX - r.left) / r.width, 0), 1);
  };

  const onTrackDown = (e: PointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    setScrubbing(true);
    seek(fraction(e.clientX) * length);
  };
  const onTrackMove = (e: PointerEvent<HTMLDivElement>) => {
    const f = fraction(e.clientX);
    setHover(f);
    if (scrubbing) seek(f * length);
  };

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const v = video.current;
    if (!v) return;
    const k = e.key.toLowerCase();
    if (k === " " || k === "k") toggle();
    else if (k === "arrowleft") seek(v.currentTime - (e.shiftKey ? 1 : 5));
    else if (k === "arrowright") seek(v.currentTime + (e.shiftKey ? 1 : 5));
    else if (k === ",") (v.pause(), seek(v.currentTime - FRAME));
    else if (k === ".") (v.pause(), seek(v.currentTime + FRAME));
    else if (k === "m") setMutedTo(!muted);
    else if (k === "f") void fullscreen();
    else if (k === "home") seek(0);
    else return;
    e.preventDefault();
    poke();
  };

  const setMutedTo = (m: boolean) => {
    if (video.current) video.current.muted = m;
    setMuted(m);
  };

  const fullscreen = async () => {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await wrap.current?.requestFullscreen();
  };

  const hoverMarker = hover != null ? markers.find((m) => hover * length >= m.start && hover * length < m.end) : null;
  const showControls = !playing || !idle || scrubbing;

  return (
    <div
      ref={wrap}
      tabIndex={0}
      onKeyDown={onKey}
      onPointerMove={poke}
      onPointerLeave={() => playing && setIdle(true)}
      className={clsx(
        "group/player relative overflow-hidden bg-black outline-none select-none",
        full ? "rounded-none" : "rounded-[var(--radius-card)] ring-1 ring-white/[0.07]",
        !showControls && "cursor-none",
        className,
      )}
    >
      <video
        ref={video}
        src={src}
        poster={poster}
        autoPlay={autoPlay}
        playsInline
        preload="metadata"
        className="block h-full w-full object-contain"
        onClick={toggle}
        onDoubleClick={() => void fullscreen()}
        onPlay={() => (setPlaying(true), poke())}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onLoadedMetadata={(e) => setLength(e.currentTarget.duration)}
        onDurationChange={(e) => setLength(e.currentTarget.duration)}
        onTimeUpdate={(e) => !scrubbing && setTime(e.currentTarget.currentTime)}
        onProgress={(e) => {
          const b = e.currentTarget.buffered;
          if (b.length) setBuffered(b.end(b.length - 1));
        }}
        onVolumeChange={(e) => (setVolume(e.currentTarget.volume), setMuted(e.currentTarget.muted))}
      />

      {!playing && (
        <button
          onClick={toggle}
          aria-label="Play"
          className="absolute top-1/2 left-1/2 flex size-16 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-black/45 text-white ring-1 ring-white/25 backdrop-blur-md transition-transform hover:scale-105"
        >
          <Play className="ml-1 size-7 fill-current" />
        </button>
      )}

      {current && (
        <div
          className={clsx(
            "pointer-events-none absolute top-3 left-3 flex max-w-[70%] items-center gap-2 rounded-lg bg-black/55 px-2.5 py-1.5 text-[11.5px] text-white/90 backdrop-blur-md transition-opacity duration-300",
            showControls ? "opacity-100" : "opacity-0",
          )}
        >
          <span className="size-1.5 rounded-full" style={{ background: sceneTint(current.scene) }} />
          <span className="font-mono text-[10.5px] text-white/70">{current.shot}</span>
          <span className="truncate">{current.label}</span>
        </div>
      )}

      <div
        className={clsx(
          "absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/45 to-transparent px-4 pt-12 pb-3 transition-opacity duration-300",
          showControls ? "opacity-100" : "pointer-events-none opacity-0",
        )}
      >
        {/* timeline */}
        <div
          ref={track}
          className="group/track relative h-5 cursor-pointer"
          onPointerDown={onTrackDown}
          onPointerMove={onTrackMove}
          onPointerUp={() => setScrubbing(false)}
          onPointerLeave={() => setHover(null)}
        >
          <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 overflow-hidden rounded-full bg-white/15 transition-[height] group-hover/track:h-1.5">
            <div className="absolute inset-y-0 left-0 bg-white/20" style={{ width: `${(buffered / (length || 1)) * 100}%` }} />
            <div className="absolute inset-y-0 left-0 bg-amber" style={{ width: `${(time / (length || 1)) * 100}%` }} />
          </div>
          {markers.slice(1).map((m) => (
            <div
              key={m.shot}
              className="absolute top-1/2 h-2.5 w-[2px] -translate-y-1/2 rounded-full bg-black/70"
              style={{ left: `${(m.start / (length || 1)) * 100}%` }}
            />
          ))}
          {markers.map((m) => (
            <div
              key={`tint-${m.shot}`}
              className="absolute top-[calc(50%+6px)] h-[3px] rounded-full opacity-70"
              style={{
                left: `calc(${(m.start / (length || 1)) * 100}% + 2px)`,
                width: `calc(${((m.end - m.start) / (length || 1)) * 100}% - 4px)`,
                background: sceneTint(m.scene),
              }}
            />
          ))}
          <div
            className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow ring-2 ring-amber transition-transform group-hover/track:scale-110"
            style={{ left: `${(time / (length || 1)) * 100}%` }}
          />
          {hover != null && length > 0 && (
            <div
              className="pointer-events-none absolute bottom-6 -translate-x-1/2 rounded-md bg-ink-800/95 px-2 py-1 text-center text-[11px] whitespace-nowrap text-fg shadow-[var(--shadow-pop)]"
              style={{ left: `${hover * 100}%` }}
            >
              <span className="font-mono">{clock(hover * length)}</span>
              {hoverMarker && <span className="ml-1.5 text-fg-3">· {hoverMarker.shot}</span>}
            </div>
          )}
        </div>

        {/* buttons */}
        <div className="mt-1.5 flex items-center gap-1 text-white">
          <PlayerButton label={playing ? "Pause (k)" : "Play (k)"} onClick={toggle}>
            {playing ? <Pause className="size-[18px] fill-current" /> : <Play className="size-[18px] fill-current" />}
          </PlayerButton>
          <PlayerButton label="Back 5 s (←)" onClick={() => seek(time - 5)}>
            <Rewind className="size-4" />
          </PlayerButton>
          <div className="group/vol flex items-center">
            <PlayerButton label={muted ? "Unmute (m)" : "Mute (m)"} onClick={() => setMutedTo(!muted)}>
              {muted || volume === 0 ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
            </PlayerButton>
            <input
              aria-label="Volume"
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={muted ? 0 : volume}
              onChange={(e) => {
                const v = Number(e.target.value);
                if (video.current) (video.current.volume = v), (video.current.muted = v === 0);
              }}
              className="ml-1 h-1 w-0 cursor-pointer accent-amber opacity-0 transition-all duration-200 group-hover/vol:w-20 group-hover/vol:opacity-100"
            />
          </div>
          <span className="ml-2 font-mono text-[11.5px] text-white/85 tabular-nums">
            {clock(time)} <span className="text-white/40">/ {clock(length)}</span>
          </span>
          <div className="flex-1" />
          <button
            className="rounded-md px-2 py-1 font-mono text-[11px] text-white/80 hover:bg-white/10"
            onClick={() => {
              const next = RATES[(RATES.indexOf(rate) + 1) % RATES.length];
              if (video.current) video.current.playbackRate = next;
              setRate(next);
            }}
            title="Playback speed"
          >
            {rate}×
          </button>
          <PlayerButton label={full ? "Exit full screen (f)" : "Full screen (f)"} onClick={() => void fullscreen()}>
            {full ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
          </PlayerButton>
        </div>
      </div>
    </div>
  );
}

function PlayerButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button
      aria-label={label}
      title={label}
      onClick={onClick}
      className="flex size-8 items-center justify-center rounded-lg text-white/90 transition-colors hover:bg-white/10 hover:text-white"
    >
      {children}
    </button>
  );
}
