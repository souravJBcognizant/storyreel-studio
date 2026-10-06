import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Cpu, KeyRound, MonitorSmartphone, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { PageHeader } from "../components/AppShell";
import { api } from "../lib/api";

export function SettingsPage() {
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  return (
    <>
      <PageHeader
        eyebrow="Settings"
        title="Providers & engine"
        subtitle="Keys live in the .env file at the repository root and never leave the backend. This page only shows whether each one is set."
      />
      {data && (
        <div className="grid gap-5 px-8 py-7 lg:grid-cols-2">
          <Card
            icon={<KeyRound className="size-4" />}
            title="Claude"
            ok={data.providers.anthropic.configured}
            rows={[
              ["Key", data.providers.anthropic.configured ? "set" : `missing — add ${data.providers.anthropic.env_var} to .env`],
              ["Important tasks", data.providers.anthropic.model],
              ["Routine steps", data.providers.anthropic.routine_model],
              ["Used for", data.providers.anthropic.role],
            ]}
          />
          <Card
            icon={<KeyRound className="size-4" />}
            title="OpenAI"
            ok={data.providers.openai.configured}
            rows={[
              ["Key", data.providers.openai.configured ? "set" : `missing — add ${data.providers.openai.env_var} to .env`],
              ["Image model", data.providers.openai.model ?? "set OPENAI_IMAGE_MODEL in .env"],
              ["Used for", data.providers.openai.role],
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
