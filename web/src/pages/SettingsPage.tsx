import clsx from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Cloud, Cpu, KeyRound, Laptop, MonitorSmartphone, RefreshCw, Save, XCircle } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { PageHeader } from "../components/AppShell";
import { Button } from "../components/ui";
import { api, type Settings, type SettingsUpdate } from "../lib/api";

type Form = SettingsUpdate & { anthropic_api_key: string; openai_api_key: string };

function formFrom(data: Settings): Form {
  return {
    mode: data.mode,
    anthropic_api_key: "",
    clear_anthropic_api_key: false,
    claude_model: data.editable.claude_model,
    claude_routine_model: data.editable.claude_routine_model,
    openai_api_key: "",
    clear_openai_api_key: false,
    openai_image_model: data.editable.openai_image_model,
    ollama_base_url: data.editable.ollama_base_url,
    ollama_model: data.editable.ollama_model,
    ollama_timeout_seconds: data.editable.ollama_timeout_seconds,
    ollama_vision_model: data.editable.ollama_vision_model,
  };
}

export function SettingsPage() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [form, setForm] = useState<Form | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (query.data && !form) setForm(formFrom(query.data));
  }, [query.data, form]);

  const accept = (data: Settings) => {
    qc.setQueryData(["settings"], data);
    void qc.invalidateQueries({ queryKey: ["agent-network"] });
    setForm(formFrom(data));
    setSaved(true);
    window.setTimeout(() => setSaved(false), 3000);
  };
  const save = useMutation({
    mutationFn: (value: Form) => api.saveSettings({
      ...value,
      anthropic_api_key: value.anthropic_api_key.trim() || undefined,
      openai_api_key: value.openai_api_key.trim() || undefined,
    }),
    onSuccess: accept,
  });
  const reload = useMutation({ mutationFn: api.reloadSettings, onSuccess: accept });
  const data = query.data;
  const busy = save.isPending || reload.isPending;
  const error = save.error ?? reload.error ?? query.error;

  return (
    <>
      <PageHeader
        eyebrow="Settings"
        title="Providers & engine"
        subtitle="Choose where the creative AI runs. Settings are saved only to this project's local .env file."
      />
      <div className="px-8 py-7">
        {!data || !form ? (
          <section className="card p-5 text-[13px] text-fg-2">{query.isLoading ? "Loading provider settings…" : error?.message ?? "Settings are unavailable."}</section>
        ) : (
          <>
            <section className="card overflow-hidden">
              <div className="border-b border-white/[0.06] px-5 py-4">
                <h2 className="text-[15px] font-semibold text-fg">AI mode</h2>
                <p className="mt-1 text-[12px] text-fg-3">Switching affects new jobs. A job already running finishes with the settings it started with.</p>
              </div>
              <div className="grid gap-3 p-5 sm:grid-cols-2">
                <ModeButton
                  selected={form.mode === "full"}
                  icon={<Cloud className="size-5" />}
                  title="Online"
                  detail="Anthropic plans and inspects; OpenAI creates reference art and keyframes."
                  onClick={() => setForm({ ...form, mode: "full" })}
                />
                <ModeButton
                  selected={form.mode === "local"}
                  icon={<Laptop className="size-5" />}
                  title="Local Ollama"
                  detail="Planning stays on this laptop. Visual inspection and generated keyframes are unavailable with a text-only model."
                  onClick={() => setForm({ ...form, mode: "local" })}
                />
              </div>

              <div className="border-t border-white/[0.06] p-5">
                {form.mode === "full" ? (
                  <div className="grid gap-5 lg:grid-cols-2">
                    <fieldset className="space-y-3">
                      <legend className="mb-3 text-[13px] font-semibold text-fg">Anthropic</legend>
                      <SecretField
                        label="API key"
                        saved={data.editable.anthropic_key_set}
                        value={form.anthropic_api_key}
                        clear={!!form.clear_anthropic_api_key}
                        onValue={(value) => setForm({ ...form, anthropic_api_key: value, clear_anthropic_api_key: false })}
                        onClear={(value) => setForm({ ...form, clear_anthropic_api_key: value, anthropic_api_key: "" })}
                      />
                      <Field label="Important-task model" value={form.claude_model} onChange={(value) => setForm({ ...form, claude_model: value })} />
                      <Field label="Routine-task model" value={form.claude_routine_model} onChange={(value) => setForm({ ...form, claude_routine_model: value })} />
                    </fieldset>
                    <fieldset className="space-y-3">
                      <legend className="mb-3 text-[13px] font-semibold text-fg">OpenAI images</legend>
                      <SecretField
                        label="API key"
                        saved={data.editable.openai_key_set}
                        value={form.openai_api_key}
                        clear={!!form.clear_openai_api_key}
                        onValue={(value) => setForm({ ...form, openai_api_key: value, clear_openai_api_key: false })}
                        onClear={(value) => setForm({ ...form, clear_openai_api_key: value, openai_api_key: "" })}
                      />
                      <Field label="Image model" value={form.openai_image_model} placeholder="Use the application default" onChange={(value) => setForm({ ...form, openai_image_model: value })} />
                      <p className="rounded-lg border border-white/[0.06] bg-ink-900/50 px-3 py-2.5 text-[11.5px] leading-relaxed text-fg-3">Existing keys are never displayed. Leave a key blank to keep it, paste a replacement to change it, or select “Remove saved key.”</p>
                    </fieldset>
                  </div>
                ) : (
                  <div className="grid gap-4 lg:grid-cols-2">
                    <Field label="Ollama address" value={form.ollama_base_url} placeholder="http://127.0.0.1:11434" onChange={(value) => setForm({ ...form, ollama_base_url: value })} />
                    <Field label="Planning model" value={form.ollama_model} placeholder="qwen3:4b" required onChange={(value) => setForm({ ...form, ollama_model: value })} />
                    <Field label="Vision model (optional)" value={form.ollama_vision_model} placeholder="Leave blank for text-only mode" onChange={(value) => setForm({ ...form, ollama_vision_model: value })} hint="Use a genuinely multimodal Ollama model here to enable image inspection." />
                    <Field label="Request timeout (seconds)" type="number" value={String(form.ollama_timeout_seconds)} onChange={(value) => setForm({ ...form, ollama_timeout_seconds: Number(value) })} />
                  </div>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-3 border-t border-white/[0.06] bg-ink-900/30 px-5 py-4">
                <Button variant="primary" icon={<Save className="size-4" />} loading={save.isPending} disabled={busy || (form.mode === "local" && !form.ollama_model.trim())} onClick={() => save.mutate(form)}>
                  Save & reload
                </Button>
                <Button icon={<RefreshCw className="size-4" />} loading={reload.isPending} disabled={busy} onClick={() => reload.mutate()}>
                  Reload from .env
                </Button>
                {saved && <span className="text-[12px] font-medium text-ok">Saved and active for new jobs.</span>}
                {error && <span role="alert" className="text-[12px] text-bad">{error.message}</span>}
              </div>
            </section>

            <div className="mt-5 grid gap-5 lg:grid-cols-2">
              <Card
                icon={<KeyRound className="size-4" />}
                title={data.providers.language.name}
                ok={data.providers.language.configured}
                rows={[["Configuration", data.providers.language.configured ? "ready" : `missing — ${data.providers.language.env_var}`], ["Important tasks", data.providers.language.model], ["Routine steps", data.providers.language.routine_model], ["Used for", data.providers.language.role]]}
              />
              <Card
                icon={<KeyRound className="size-4" />}
                title={`${data.providers.vision.name} vision`}
                ok={data.mode === "local" || data.providers.vision.configured}
                rows={[["Configuration", data.providers.vision.configured ? "ready" : data.mode === "local" ? "unavailable with current local setup" : `missing — ${data.providers.vision.env_var}`], ["Vision model", data.providers.vision.model ?? "not configured"], ["Used for", data.providers.vision.role]]}
              />
              <Card
                icon={<KeyRound className="size-4" />}
                title={data.providers.images.name}
                ok={data.mode === "local" || data.providers.images.configured}
                rows={[["Configuration", data.providers.images.configured ? "ready" : data.mode === "local" ? "skipped in local mode" : `missing — ${data.providers.images.env_var}`], ["Image model", data.providers.images.model ?? "not configured"], ["Used for", data.providers.images.role]]}
              />
              <Card icon={<Cpu className="size-4" />} title={data.engine.name} ok={data.engine.model_present} rows={[["Runtime", `${data.engine.runtime} @ ${data.engine.runtime_rev ?? "?"}`], ["Model pack", data.engine.model_present ? `${data.engine.model_gb} GB on disk` : "not downloaded"], ["Runs", "Locally, one job at a time"]]} />
              <Card icon={<MonitorSmartphone className="size-4" />} title="This machine" ok rows={[["Chip", data.machine.chip], ["Memory", data.machine.memory_gb ? `${data.machine.memory_gb} GB unified` : "—"], ["System", data.machine.os]]} />
            </div>
          </>
        )}
      </div>
    </>
  );
}

function ModeButton({ selected, icon, title, detail, onClick }: { selected: boolean; icon: ReactNode; title: string; detail: string; onClick: () => void }) {
  return <button type="button" aria-pressed={selected} onClick={onClick} className={clsx("rounded-xl border p-4 text-left transition", selected ? "border-amber/50 bg-amber/[0.08]" : "border-white/[0.08] bg-ink-900/40 hover:border-white/[0.16]")}><span className={clsx("flex size-9 items-center justify-center rounded-lg", selected ? "bg-amber/15 text-amber" : "bg-ink-800 text-fg-3")}>{icon}</span><span className="mt-3 block text-[14px] font-semibold text-fg">{title}</span><span className="mt-1 block text-[11.5px] leading-relaxed text-fg-3">{detail}</span></button>;
}

function Field({ label, value, onChange, placeholder, hint, type = "text", required = false }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; hint?: string; type?: string; required?: boolean }) {
  return <label className="block text-[11.5px] text-fg-3"><span>{label}{required && <span className="text-amber"> *</span>}</span><input type={type} min={type === "number" ? 10 : undefined} max={type === "number" ? 3600 : undefined} className="mt-1.5 h-10 w-full rounded-lg border border-white/[0.09] bg-ink-900 px-3 font-mono text-[12px] text-fg outline-none transition placeholder:text-fg-4 focus:border-amber/50" value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />{hint && <span className="mt-1.5 block text-[10.5px] leading-relaxed text-fg-4">{hint}</span>}</label>;
}

function SecretField({ label, saved, value, clear, onValue, onClear }: { label: string; saved: boolean; value: string; clear: boolean; onValue: (value: string) => void; onClear: (value: boolean) => void }) {
  return <div><Field label={label} type="password" value={value} placeholder={saved ? "Saved — leave blank to keep" : "Paste API key"} onChange={onValue} />{saved && <label className="mt-2 flex items-center gap-2 text-[10.5px] text-fg-4"><input type="checkbox" checked={clear} onChange={(event) => onClear(event.target.checked)} className="accent-amber" />Remove saved key when saving</label>}</div>;
}

function Card({ icon, title, ok, rows }: { icon: ReactNode; title: string; ok: boolean; rows: [string, string][] }) {
  return <section className="card p-5"><div className="flex items-center gap-2.5"><span className="flex size-8 items-center justify-center rounded-lg border border-white/[0.08] bg-ink-800 text-fg-2">{icon}</span><h2 className="text-[14.5px] font-semibold text-fg">{title}</h2><span className="ml-auto">{ok ? <CheckCircle2 className="size-5 text-ok" /> : <XCircle className="size-5 text-warn" />}</span></div><dl className="mt-4 grid grid-cols-[130px_minmax(0,1fr)] gap-x-4 gap-y-2.5 text-[12.5px]">{rows.map(([key, value]) => <div key={key} className="contents"><dt className="text-fg-3">{key}</dt><dd className="break-words font-mono text-[11.5px] text-fg-2">{value}</dd></div>)}</dl></section>;
}
