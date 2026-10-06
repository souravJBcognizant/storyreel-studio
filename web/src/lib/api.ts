// Typed client for the studio API (storyvid/api). Shapes mirror storyvid/api/store.py.

export type StageStatus =
  | "pending"
  | "queued"
  | "running"
  | "awaiting_approval"
  | "done"
  | "skipped"
  | "failed";
export type Engine = "claude" | "openai" | "ltx" | "ffmpeg" | "user";
export type JobStatus = "queued" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled";
export type ShotStatus = "pending" | "rendering" | "checking" | "done" | "needs_review";

export interface Stage {
  key: string;
  label: string;
  owner: string;
  engine: Engine;
  model?: string;
  detail: string;
  checkpoint?: boolean;
  status: StageStatus;
}

export interface Progress {
  phase: string;
  shots_total: number;
  shots_done: number;
  takes_done: number;
  renders_done: number;
  render_s_total: number;
  current_shot: string | null;
  current_take: number | null;
  eta_s: number | null;
  started: number;
  last_event: number;
  error: string | null;
}

export interface Job {
  id: string;
  production: string;
  kind: string;
  status: JobStatus;
  created: number;
  started: number | null;
  ended: number | null;
  pid: number | null;
  returncode: number | null;
  error: string | null;
  plan: string;
  out: string;
  log: string;
  summary: Progress | null;
  progress?: Progress | null;
}

export interface Take {
  index: number;
  seed: number;
  render_s: number;
  cached: boolean;
  seconds: number;
  heard: string | null;
  wer: number | null;
  voice: number | null;
  identity: number | null;
  continuity: number | null;
  heads: string | null;
  failures: string[];
  passed: boolean;
  path: string;
  contact: string | null;
}

export interface Shot {
  id: string;
  start: "fresh" | "continue" | "anchor";
  from: string | null;
  image: string | null;
  character: string | null;
  line: string | null;
  action: string;
  camera: string;
  seconds: number | null;
  identity_check: boolean;
  takes_planned: number;
  status: ShotStatus;
  current_take: number | null;
  takes: Take[];
  chosen: number | null;
  prompt: string | null;
}

export interface Scene {
  id: string;
  setting: string;
  audio: string;
  shots: Shot[];
}

export interface Character {
  id: string;
  bible: string;
  voice_phrase: string;
  image: string | null;
  voice_refs: number;
}

export interface FilmMarker {
  shot: string;
  scene: string;
  start: number;
  end: number;
  label: string;
}

export interface Film {
  path: string;
  duration: number | null;
  markers: FilmMarker[];
  report: string | null;
}

export interface ProductionSummary {
  id: string;
  title: string;
  created: number;
  updated: number;
  source: string;
  target_seconds: number;
  steps: Record<string, StageStatus>;
  first_frame: string | null;
  poster: string | null;
  film_seconds: number | null;
  shots_done: number;
  takes: number;
  active_job: Job | null;
  progress: Progress | null;
}

export interface Production extends ProductionSummary {
  story: string;
  stages: Stage[];
  characters: Character[];
  props: Record<string, string>;
  scenes: Scene[];
  film: Film | null;
  out: string | null;
  jobs: Job[];
  can_render: boolean;
}

export interface FileEntry {
  name: string;
  path: string;
  kind: "dir" | "video" | "image" | "audio" | "text" | "other";
  size: number | null;
  modified: number;
  duration: number | null;
  items: number | null;
}

export interface Listing {
  path: string;
  parent: string | null;
  entries: FileEntry[];
}

export interface FileRoot {
  key: string;
  label: string;
  exists: boolean;
}

export interface Settings {
  providers: {
    anthropic: { configured: boolean; env_var: string; model: string; routine_model: string; role: string };
    openai: { configured: boolean; env_var: string; model: string | null; role: string };
  };
  engine: {
    name: string;
    runtime: string;
    runtime_rev: string | null;
    model_present: boolean;
    model_gb: number;
  };
  machine: { chip: string; memory_gb: number | null; os: string };
}

export interface PipelineEvent {
  t: number;
  type: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  settings: () => request<Settings>("/api/settings"),
  productions: () => request<ProductionSummary[]>("/api/productions"),
  production: (id: string) => request<Production>(`/api/productions/${id}`),
  createProduction: (form: FormData) =>
    request<Production>("/api/productions", { method: "POST", body: form }),
  deleteProduction: (id: string) => request<{ deleted: string }>(`/api/productions/${id}`, { method: "DELETE" }),
  startRender: (id: string) => request<Job>(`/api/productions/${id}/jobs?kind=render`, { method: "POST" }),
  jobs: () => request<Job[]>("/api/jobs"),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  cancelJob: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  jobLog: (id: string, lines = 300) => request<string>(`/api/jobs/${id}/log?lines=${lines}`),
  jobEvents: (id: string) => request<PipelineEvent[]>(`/api/jobs/${id}/events`),
  roots: () => request<FileRoot[]>("/api/files/roots"),
  files: (path: string) => request<Listing>(`/api/files?path=${encodeURIComponent(path)}`),
  text: (path: string) => request<string>(`/api/text?path=${encodeURIComponent(path)}`),
};

export const mediaUrl = (path: string) => `/media/${path.split("/").map(encodeURIComponent).join("/")}`;
export const thumbUrl = (path: string, at = 1, w = 480) =>
  `/api/thumb?path=${encodeURIComponent(path)}&at=${at}&w=${w}`;
