import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Cpu, KeyRound, MonitorSmartphone, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { PageHeader } from "../components/AppShell";
import { api } from "../lib/api";

export function SettingsPage() {
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const providersReady = Boolean(data?.providers.language && data?.providers.vision && data?.providers.images);
  return (
    <>
      <PageHeader
        eyebrow="Settings"
        title="Providers & engine"
        subtitle={data?.mode === "local" ? "Local mode is active. Visual inspection and generated keyframes are deliberately skipped." : "Full mode is active. Keys live in the repository's .env file and never leave the backend."}
      />
      {data && !providersReady && (
        <div className="px-8 py-7">
          <section className="card p-5 text-[13px] text-fg-2">Provider settings are reloading. Refresh once the API restart finishes.</section>
        </div>
      )}
      {data && providersReady && (
        <div className="grid gap-5 px-8 py-7 lg:grid-cols-2">
          <Card
            icon={<KeyRound className="size-4" />}
            title={data.providers.language.name}
            ok={data.providers.language.configured}
            rows={[
              ["Configuration", data.providers.language.configured ? "ready" : `missing — add ${data.providers.language.env_var} to .env`],
              ["Important tasks", data.providers.language.model],
              ["Routine steps", data.providers.language.routine_model],
              ["Used for", data.providers.language.role],
            ]}
          />
          <Card
            icon={<KeyRound className="size-4" />}
            title={`${data.providers.vision.name} vision`}
            ok={data.mode === "local" || data.providers.vision.configured}
            rows={[
              ["Configuration", data.providers.vision.configured ? "ready" : data.mode === "local" ? "unavailable in local mode" : `missing — add ${data.providers.vision.env_var} to .env`],
              ["Vision model", data.providers.vision.model ?? "not configured"],
              ["Used for", data.providers.vision.role],
            ]}
          />
          <Card
            icon={<KeyRound className="size-4" />}
            title={data.providers.images.name}
            ok={data.mode === "local" || data.providers.images.configured}
            rows={[
              ["Configuration", data.providers.images.configured ? "ready" : data.mode === "local" ? "unavailable in local mode" : `missing — add ${data.providers.images.env_var} to .env`],
              ["Image model", data.providers.images.model ?? "not configured"],
              ["Used for", data.providers.images.role],
            ]}
          />
          <Card
            icon={<Cpu className="size-4" />}
            title={data.engine.name}
            ok={data.engine.model_present}
            rows={[
              ["Runtime", `${data.engine.runtime} @ ${data.engine.runtime_rev ?? "?"}`],
              ["Model pack", data.engine.model_present ? `${data.engine.model_gb} GB on disk` : "not downloaded"],
              ["Runs", "Locally, one job at a time"],
            ]}
          />
          <Card
            icon={<MonitorSmartphone className="size-4" />}
            title="This machine"
            ok
            rows={[
              ["Chip", data.machine.chip],
              ["Memory", data.machine.memory_gb ? `${data.machine.memory_gb} GB unified` : "—"],
              ["System", data.machine.os],
            ]}
          />
        </div>
      )}
    </>
  );
}

function Card({ icon, title, ok, rows }: { icon: ReactNode; title: string; ok: boolean; rows: [string, string][] }) {
  return (
    <section className="card p-5">
      <div className="flex items-center gap-2.5">
        <span className="flex size-8 items-center justify-center rounded-lg border border-white/[0.08] bg-ink-800 text-fg-2">{icon}</span>
        <h2 className="text-[14.5px] font-semibold text-fg">{title}</h2>
        <span className="ml-auto">
          {ok ? <CheckCircle2 className="size-5 text-ok" /> : <XCircle className="size-5 text-warn" />}
        </span>
      </div>
      <dl className="mt-4 grid grid-cols-[130px_minmax(0,1fr)] gap-x-4 gap-y-2.5 text-[12.5px]">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-fg-3">{k}</dt>
            <dd className="font-mono text-[11.5px] break-words text-fg-2">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
