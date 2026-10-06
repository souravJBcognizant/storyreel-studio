import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  AudioLines,
  ChevronRight,
  ExternalLink,
  File as FileIcon,
  FileText,
  Film,
  Folder,
  FolderOpen,
  ImageIcon,
  LayoutGrid,
  List,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api, mediaUrl, thumbUrl, type FileEntry } from "../lib/api";
import { ago, bytes, clock, plural } from "../lib/format";
import { EmptyState, IconButton } from "./ui";
import { VideoPlayer } from "./VideoPlayer";

const KIND_ICON = { dir: Folder, video: Film, image: ImageIcon, audio: AudioLines, text: FileText, other: FileIcon };

export function FileBrowser({ root, className }: { root: string; className?: string }) {
  const [path, setPath] = useState(root);
  const [selected, setSelected] = useState<FileEntry | null>(null);
  const [view, setView] = useState<"grid" | "list">("grid");
  useEffect(() => (setPath(root), setSelected(null)), [root]);

  const listing = useQuery({ queryKey: ["files", path], queryFn: () => api.files(path) });
  const crumbs = path.split("/");

  const open = (e: FileEntry) => {
    if (e.kind === "dir") {
      setPath(e.path);
      setSelected(null);
    } else setSelected(e);
  };

  return (
    <div className={clsx("grid min-h-[560px] gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(340px,440px)]", className)}>
      <div className="card flex min-w-0 flex-col">
        <div className="flex items-center gap-2 border-b border-white/[0.06] px-4 py-2.5">
          <nav className="flex min-w-0 flex-1 items-center gap-1 text-[12.5px]">
            {crumbs.map((c, i) => {
              const target = crumbs.slice(0, i + 1).join("/");
              const last = i === crumbs.length - 1;
              const rootLevel = root.split("/").length - 1;
              if (i < rootLevel) return null;
              return (
                <span key={target} className="flex min-w-0 items-center gap-1">
                  {i > rootLevel && <ChevronRight className="size-3.5 shrink-0 text-fg-4" />}
                  <button
                    onClick={() => (setPath(target), setSelected(null))}
                    className={clsx("truncate rounded px-1 py-0.5", last ? "font-medium text-fg" : "text-fg-3 hover:text-fg")}
                  >
                    {c}
                  </button>
                </span>
              );
            })}
          </nav>
          <IconButton label="Grid view" onClick={() => setView("grid")} className={view === "grid" ? "text-fg" : "text-fg-4"}>
            <LayoutGrid className="size-4" />
          </IconButton>
          <IconButton label="List view" onClick={() => setView("list")} className={view === "list" ? "text-fg" : "text-fg-4"}>
            <List className="size-4" />
          </IconButton>
        </div>

        <div className="flex-1 overflow-y-auto p-3">
          {listing.isLoading && (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
              {Array.from({ length: 8 }, (_, i) => (
                <div key={i} className="skeleton aspect-[4/3]" />
              ))}
            </div>
          )}
          {listing.error && <EmptyState icon={<FolderOpen className="size-5" />} title="Can't open this folder">{String(listing.error)}</EmptyState>}
          {listing.data && !listing.data.entries.length && (
            <EmptyState icon={<FolderOpen className="size-5" />} title="Empty folder">Nothing has been written here yet.</EmptyState>
          )}
          {listing.data && view === "grid" && (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
              {listing.data.entries.map((e) => (
                <GridItem key={e.path} entry={e} active={selected?.path === e.path} onOpen={() => open(e)} />
              ))}
            </div>
          )}
          {listing.data && view === "list" && (
            <table className="w-full text-[12.5px]">
              <tbody>
                {listing.data.entries.map((e) => {
                  const Icon = KIND_ICON[e.kind];
                  return (
                    <tr
                      key={e.path}
                      onClick={() => open(e)}
                      className={clsx("cursor-pointer border-b border-white/[0.04]", selected?.path === e.path ? "bg-amber/[0.06]" : "hover:bg-white/[0.03]")}
                    >
                      <td className="flex items-center gap-2.5 px-2 py-2 text-fg">
                        <Icon className={clsx("size-4 shrink-0", e.kind === "dir" ? "text-amber" : "text-fg-3")} />
                        <span className="truncate">{e.name}</span>
                      </td>
                      <td className="px-2 text-right font-mono text-[11px] text-fg-3">
                        {e.kind === "dir" ? plural(e.items ?? 0, "item") : e.duration ? clock(e.duration) : bytes(e.size)}
                      </td>
                      <td className="w-24 px-2 text-right text-[11px] text-fg-4">{ago(e.modified)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <Preview entry={selected} />
    </div>
  );
}

function GridItem({ entry, active, onOpen }: { entry: FileEntry; active: boolean; onOpen: () => void }) {
  const Icon = KIND_ICON[entry.kind];
  const visual = entry.kind === "video" || entry.kind === "image";
  return (
    <button
      onClick={onOpen}
      onDoubleClick={() => entry.kind !== "dir" && window.open(mediaUrl(entry.path), "_blank")}
      className={clsx(
        "group flex flex-col justify-start overflow-hidden rounded-xl border text-left transition-all",
        active ? "border-amber/50 bg-amber/[0.05]" : "border-white/[0.06] bg-ink-800/60 hover:border-white/[0.14]",
      )}
    >
      <div className="relative flex aspect-[4/3] items-center justify-center overflow-hidden bg-ink-900">
        {visual ? (
          <img src={thumbUrl(entry.path, 1, 320)} alt="" loading="lazy" className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105" />
        ) : (
          <Icon className={clsx("size-8", entry.kind === "dir" ? "text-amber/80" : "text-fg-4")} strokeWidth={1.4} />
        )}
        {entry.kind === "video" && entry.duration != null && (
          <span className="absolute right-1.5 bottom-1.5 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[10px] text-white/90">{clock(entry.duration)}</span>
        )}
      </div>
      <div className="px-2.5 py-2">
        <div className="truncate text-[12px] font-medium text-fg">{entry.name}</div>
        <div className="mt-0.5 text-[10.5px] text-fg-4">{entry.kind === "dir" ? plural(entry.items ?? 0, "item") : bytes(entry.size)}</div>
      </div>
    </button>
  );
}

function Preview({ entry }: { entry: FileEntry | null }) {
  const text = useQuery({
    queryKey: ["text", entry?.path],
    queryFn: () => api.text(entry!.path),
    enabled: entry?.kind === "text",
  });
  if (!entry)
    return (
      <div className="card hidden lg:block">
        <EmptyState icon={<Film className="size-5" />} title="Preview">
          Select a video, image, audio clip or text file to view it here. Double-click opens it in a new tab.
        </EmptyState>
      </div>
    );
  return (
    <div className="card flex min-w-0 flex-col overflow-hidden lg:sticky lg:top-6 lg:max-h-[calc(100vh-120px)]">
      <div className="flex items-center justify-between gap-2 border-b border-white/[0.06] px-4 py-2.5">
        <div className="min-w-0">
          <div className="truncate text-[13px] font-medium text-fg">{entry.name}</div>
          <div className="text-[11px] text-fg-4">
            {bytes(entry.size)} · modified {ago(entry.modified)}
            {entry.duration != null && ` · ${clock(entry.duration)}`}
          </div>
        </div>
        <a href={mediaUrl(entry.path)} target="_blank" rel="noreferrer" className="rounded-lg p-1.5 text-fg-3 hover:bg-white/[0.06] hover:text-fg" title="Open in new tab">
          <ExternalLink className="size-4" />
        </a>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">
        {entry.kind === "video" && <VideoPlayer key={entry.path} src={mediaUrl(entry.path)} poster={thumbUrl(entry.path, 0.5, 960)} className="aspect-[3/2] w-full" autoPlay />}
        {entry.kind === "image" && <img src={mediaUrl(entry.path)} alt={entry.name} className="w-full rounded-lg" />}
        {entry.kind === "audio" && (
          <div className="flex flex-col items-center gap-4 py-8">
            <AudioLines className="size-10 text-amber" strokeWidth={1.3} />
            <audio key={entry.path} src={mediaUrl(entry.path)} controls autoPlay className="w-full" />
          </div>
        )}
        {entry.kind === "text" && (
          <pre className="font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-fg-2">{text.data ?? "Loading…"}</pre>
        )}
        {entry.kind === "other" && <p className="text-[12.5px] text-fg-3">No preview for this file type.</p>}
      </div>
    </div>
  );
}
