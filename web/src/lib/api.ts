// Typed client for the studio API (storyvid/api). Shapes mirror storyvid/api/store.py.

export type StageStatus =
  | "pending"
  | "queued"
  | "running"
  | "awaiting_approval"
  | "done"
  | "skipped"
  | "failed";
export type Engine = "claude" | "openai" | "ollama" | "local" | "ltx" | "qwen" | "ffmpeg" | "user";
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
  /** Dubbed films: who Claude saw talking, and why. */
  speaker?: string | null;
  speaker_note?: string | null;
  /** Dubbed films: the take's picture with the cast voice, and how many words were timed to the lips. */
  dub?: string | null;
  dub_revision?: number | null;
  dub_words?: string | null;
  /** Human directions used to generate this video take and its current overlay. */
  edit_prompt?: string | null;
  audio_prompt?: string | null;
}

export interface Shot {
  id: string;
  start: "fresh" | "continue" | "anchor";
  from: string | null;
  image: string | null;
  end_image: string | null;
  character: string | null;
  line: string | null;
  /** Who says the line; the character in frame unless it is delivered off camera. */
  speaker: string | null;
  delivery: "on" | "off";
  audio_source: "cast" | "original";
  has_cast_audio: boolean;
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

export interface ShotEditInput {
  action: string;
  camera: string;
  seconds: number;
  line: string;
  character: string | null;
  speaker: string | null;
  delivery: "on" | "off";
}

export interface SceneCreateInput {
  mode: "blank" | "duplicate" | "import";
  name?: string;
  setting?: string;
  audio?: string;
  action?: string;
  camera?: string;
  seconds?: number;
  source_production?: string | null;
  source_scene?: string | null;
  reuse_takes?: boolean;
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
  revision: number;
  audio_pending: boolean;
  audio_upgrade: boolean;
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
  reference_images: { role: "opening" | "guide" | "ending"; name: string; path: string }[];
  poster: string | null;
  film_seconds: number | null;
  shots_done: number;
  takes: number;
  active_job: Job | null;
  progress: Progress | null;
}

export interface AgentNetwork {
  name: string;
  front_man: string;
  agents: { name: string; description: string; model: string; tools: string[]; max_seconds: number | null }[];
  tools: { name: string; description: string; engine: "claude" | "openai" | "ollama" | "local" }[];
  llm_provider: "anthropic" | "ollama";
  local_mode: boolean;
  image_model: string | null;
}

export interface AgentProgress {
  phase: string;
  agent: string | null;
  tool: string | null;
  cost: number | null;
  last_text: string | null;
  messages: number;
  started: number;
  last_event: number;
  error: string | null;
}

export interface CastCharacter {
  id: string;
  name: string;
  bible: string;
  voice_phrase: string;
  head_query: string;
}

export interface Beat {
  action: string;
  character?: string | null;
  line?: string | null;
  delivery?: string | null;
}

export interface KeyframeReview {
  same_character: boolean;
  differences: string[];
  matches_scene: boolean;
  prop_ok: boolean;
  single_ok?: boolean;
  score: number;
  verdict: string;
}

export interface KeyframeCandidate {
  n: number;
  frame: string;
  description: string;
  identity?: Record<string, number | null>;
  review: KeyframeReview;
  seconds: number;
}

export interface KeyframeChoice {
  chosen: number | null;
  candidates: KeyframeCandidate[];
}

export interface VoiceCandidate {
  n: number;
  description: string;
  text: string;
  path: string;
  seconds: number;
  likeness: Record<string, number>;
}

export interface VoiceClip {
  shot: string;
  scene: string;
  line: string;
  heard: string;
  wer: number;
  render_s: number;
  video: string;
  audio: string;
}

export interface Preprod {
  frame: Record<string, unknown> | null;
  cast: { style: string; characters: CastCharacter[]; props: Record<string, string> } | null;
  screenplay: {
    logline: string;
    scenes: { id: string; setting: string; audio: string; opening: string; beats: Beat[] }[];
  } | null;
  keyframes: {
    sheets: Record<string, string>;
    props: Record<string, string>;
    /** Per scene: the establishing frame, and a single (close-up) of every character who speaks in it. */
    scenes: Record<string, KeyframeChoice & { singles?: Record<string, KeyframeChoice> }>;
  } | null;
  /** An LTX voice audition, from before voice casting. */
  voice: { character: string; clips: VoiceClip[]; consistency: number | null; pairs: number[] } | null;
  /** Cast voices: per character, every candidate and the chosen one. */
  voices: Record<string, { chosen: number | null; candidates: VoiceCandidate[] }> | null;
  summary: string | null;
  conversation: PipelineEvent[];
  trace: PipelineEvent[];
}

export interface Production extends ProductionSummary {
  story: string;
  story_mode: "manual" | "ai";
  story_prompt: string | null;
  story_uses_images: boolean | null;
  story_note: string | null;
  stages: Stage[];
  characters: Character[];
  props: Record<string, string>;
  scenes: Scene[];
  film: Film | null;
  out: string | null;
  jobs: Job[];
  can_render: boolean;
  can_plan: boolean;
  can_audition: boolean;
  agent_progress: AgentProgress | null;
  preprod: Preprod | null;
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
  mode: "full" | "local";
  editable: {
    anthropic_key_set: boolean;
    openai_key_set: boolean;
    claude_model: string;
    claude_routine_model: string;
    openai_image_model: string;
    ollama_base_url: string;
    ollama_model: string;
    ollama_timeout_seconds: number;
    ollama_vision_model: string;
  };
  providers: {
    language: { name: string; provider: string; configured: boolean; env_var: string; model: string; routine_model: string; role: string };
    vision: { name: string; provider: string; configured: boolean; env_var: string; model: string | null; role: string };
    images: { name: string; provider: string; configured: boolean; env_var: string; model: string | null; role: string };
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

export interface SettingsUpdate {
  mode: "full" | "local";
  anthropic_api_key?: string;
  clear_anthropic_api_key?: boolean;
  claude_model: string;
  claude_routine_model: string;
  openai_api_key?: string;
  clear_openai_api_key?: boolean;
  openai_image_model: string;
  ollama_base_url: string;
  ollama_model: string;
  ollama_timeout_seconds: number;
  ollama_vision_model: string;
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
  saveSettings: (settings: SettingsUpdate) => request<Settings>("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  }),
  reloadSettings: () => request<Settings>("/api/settings/reload", { method: "POST" }),
  agentNetwork: () => request<AgentNetwork>("/api/agents/network"),
  productions: () => request<ProductionSummary[]>("/api/productions"),
  production: (id: string) => request<Production>(`/api/productions/${id}`),
  createProduction: (form: FormData) =>
    request<Production>("/api/productions", { method: "POST", body: form }),
  duplicateProduction: (id: string, title: string) =>
    request<Production>(`/api/productions/${id}/duplicate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  deleteProduction: (id: string) => request<{ deleted: string }>(`/api/productions/${id}`, { method: "DELETE" }),
  deleteShot: (id: string, shot: string) =>
    request<Production>(`/api/productions/${id}/shots/${shot}`, { method: "DELETE" }),
  reorderShots: (id: string, scene: string, shotIds: string[]) =>
    request<Production>(`/api/productions/${id}/scenes/${scene}/shots/order`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shot_ids: shotIds }),
    }),
  addScene: (id: string, input: SceneCreateInput) =>
    request<Production>(`/api/productions/${id}/scenes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  reorderScenes: (id: string, sceneIds: string[]) =>
    request<Production>(`/api/productions/${id}/scenes/order`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scene_ids: sceneIds }),
    }),
  updateScene: (id: string, scene: string, setting: string, audio: string) =>
    request<Production>(`/api/productions/${id}/scenes/${scene}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ setting, audio }),
    }),
  deleteScene: (id: string, scene: string) =>
    request<Production>(`/api/productions/${id}/scenes/${scene}`, { method: "DELETE" }),
  addShot: (id: string, scene: string, input: ShotEditInput & { after?: string | null }) =>
    request<Production>(`/api/productions/${id}/scenes/${scene}/shots`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  updateShot: (id: string, shot: string, input: ShotEditInput) =>
    request<Production>(`/api/productions/${id}/shots/${shot}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  setShotReference: (id: string, shot: string, edge: "start" | "end", file: File) => {
    const form = new FormData();
    form.set("frame", file);
    return request<Production>(`/api/productions/${id}/shots/${shot}/references/${edge}`, { method: "PUT", body: form });
  },
  removeShotReference: (id: string, shot: string, edge: "start" | "end") =>
    request<Production>(`/api/productions/${id}/shots/${shot}/references/${edge}`, { method: "DELETE" }),
  useNeighborReference: (id: string, shot: string, edge: "start" | "end") =>
    request<Production>(`/api/productions/${id}/shots/${shot}/references/${edge}/neighbor`, { method: "PUT" }),
  startRender: (id: string) => request<Job>(`/api/productions/${id}/jobs?kind=render`, { method: "POST" }),
  rebuildFilm: (id: string) => request<Job>(`/api/productions/${id}/jobs?kind=export`, { method: "POST" }),
  chooseAudio: (id: string, shot: string, source: "cast" | "original") =>
    request<Production>(`/api/productions/${id}/shots/${shot}/audio`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    }),
  regenerateShot: (id: string, shot: string, prompt: string) =>
    request<Job>(`/api/productions/${id}/shots/${shot}/regenerate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    }),
  regenerateOverlay: (id: string, shot: string, prompt: string) =>
    request<Job>(`/api/productions/${id}/shots/${shot}/regenerate-overlay`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    }),
  startJob: (id: string, kind: "render" | "preprod" | "audition") =>
    request<Job>(`/api/productions/${id}/jobs?kind=${kind}`, { method: "POST" }),
  recastVoice: (id: string, character: string, description: string, text: string) =>
    request<Job>(`/api/productions/${id}/voices/${character}/recast`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description, text }),
    }),
  chooseVoice: (id: string, character: string, n: number) =>
    request<Production>(`/api/productions/${id}/voices/${character}/choose?n=${n}`, { method: "POST" }),
  approve: (id: string, stage: "plan" | "keyframes" | "voice") =>
    request<Production>(`/api/productions/${id}/approve?stage=${stage}`, { method: "POST" }),
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
