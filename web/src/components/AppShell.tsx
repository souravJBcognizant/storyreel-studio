import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Clapperboard, Cpu, FolderOpen, LayoutGrid, ListChecks, Plus, Settings } from "lucide-react";
import type { ReactNode } from "react";
import { Link, NavLink, Outlet } from "react-router";
import { api, type Job } from "../lib/api";
import { pct } from "../lib/format";
import { ProgressBar } from "./ui";

const NAV = [
  { to: "/", label: "Productions", icon: LayoutGrid, end: true },
  { to: "/new", label: "New production", icon: Plus },
  { to: "/jobs", label: "Jobs", icon: ListChecks },
  { to: "/library", label: "Library", icon: FolderOpen },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function AppShell() {
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, refetchInterval: 3000 });
  const active = jobs.data?.filter((j) => ["queued", "running", "cancelling"].includes(j.status)) ?? [];
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-[244px] shrink-0 flex-col border-r border-white/[0.05] bg-ink-900/80 px-3 pt-5 pb-4 backdrop-blur md:flex">
        <Link to="/" className="mb-7 flex items-center gap-2.5 px-2.5">
          <Logo />
          <div className="leading-none">
            <div className="font-display text-[19px] font-semibold tracking-tight text-fg">Storyreel</div>
            <div className="mt-1 font-mono text-[9.5px] tracking-[0.22em] text-fg-4 uppercase">Studio</div>
          </div>
        </Link>
        <nav className="flex flex-col gap-0.5">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  "group flex h-9 items-center gap-3 rounded-lg px-2.5 text-[13px] transition-colors",
                  isActive ? "bg-white/[0.06] font-medium text-fg" : "text-fg-3 hover:bg-white/[0.03] hover:text-fg",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <Icon className={clsx("size-4", isActive ? "text-amber" : "text-fg-4 group-hover:text-fg-3")} strokeWidth={1.8} />
                  {label}
                  {to === "/jobs" && active.length > 0 && (
                    <span className="ml-auto rounded-full bg-amber/15 px-1.5 font-mono text-[10px] text-amber">{active.length}</span>
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto">
          <EngineCard active={active} />
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  );
}

function EngineCard({ active }: { active: Job[] }) {
  const running = active.find((j) => j.status === "running" || j.status === "cancelling");
  const job = useQuery({
    queryKey: ["job", running?.id],
    queryFn: () => api.job(running!.id),
    enabled: !!running,
    refetchInterval: 3000,
  });
  const p = job.data?.progress;
  return (
    <div className="rounded-xl border border-white/[0.06] bg-ink-850 p-3">
      <div className="flex items-center gap-2 text-[11.5px]">
        <Cpu className="size-3.5 text-engine-ltx" />
        <span className="font-medium text-fg-2">Render engine</span>
        <span className={clsx("ml-auto size-1.5 rounded-full", running ? "animate-pulse-soft bg-amber" : "bg-ok")} />
      </div>
      {running ? (
        <Link to={`/p/${running.production}?tab=pipeline`} className="mt-2.5 block">
          <div className="flex items-center gap-1.5 text-[12px] text-fg">
            <Clapperboard className="size-3.5 text-amber" />
            <span className="truncate">{running.production}</span>
          </div>
          <div className="mt-1 text-[11px] text-fg-3">
            {p?.current_shot ? `Shot ${p.current_shot} · take ${(p.current_take ?? 0) + 1}` : p?.phase ?? "starting…"}
            {p && ` · ${p.shots_done}/${p.shots_total}`}
          </div>
          <ProgressBar value={p ? pct(p.shots_done, p.shots_total) : 0} live className="mt-2" />
        </Link>
      ) : (
        <div className="mt-1.5 text-[11px] text-fg-3">
          {active.length ? `${active.length} job queued` : "Idle — LTX-2.5 ready on this Mac"}
        </div>
      )}
    </div>
  );
}

function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
      <defs>
        <linearGradient id="lg" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#ffc261" />
          <stop offset="1" stopColor="#d9831f" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="#1a1815" stroke="rgb(255 240 220 / 0.08)" />
      <circle cx="16" cy="16" r="9" fill="none" stroke="url(#lg)" strokeWidth="2.2" />
      <circle cx="16" cy="16" r="2.4" fill="url(#lg)" />
      {[0, 120, 240].map((a) => (
        <circle key={a} cx={16 + 5.6 * Math.sin((a * Math.PI) / 180)} cy={16 - 5.6 * Math.cos((a * Math.PI) / 180)} r="1.6" fill="url(#lg)" />
      ))}
    </svg>
  );
}

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
  children,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="border-b border-white/[0.05] px-8 pt-8 pb-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          {eyebrow && <div className="eyebrow mb-2">{eyebrow}</div>}
          <h1 className="font-display text-[30px] leading-tight font-medium tracking-tight text-fg">{title}</h1>
          {subtitle && <p className="mt-1.5 max-w-2xl text-[13.5px] leading-relaxed text-fg-3">{subtitle}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {children}
    </header>
  );
}
