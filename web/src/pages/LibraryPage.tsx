import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useState } from "react";
import { PageHeader } from "../components/AppShell";
import { FileBrowser } from "../components/FileBrowser";
import { api } from "../lib/api";

export function LibraryPage() {
  const roots = useQuery({ queryKey: ["roots"], queryFn: api.roots });
  const available = roots.data?.filter((r) => r.exists) ?? [];
  const [root, setRoot] = useState<string | null>(null);
  const current = root ?? available[0]?.key ?? null;

  return (
    <>
      <PageHeader
        eyebrow="Library"
        title="Every file the studio has made"
        subtitle="Films, individual takes, contact sheets, voice tests and logs. Click to preview, and videos play right here."
      >
        <div className="mt-5 flex gap-1.5">
          {available.map((r) => (
            <button
              key={r.key}
              onClick={() => setRoot(r.key)}
              className={clsx(
                "h-8 rounded-full border px-3.5 text-[12.5px] transition-colors",
                current === r.key ? "border-amber/40 bg-amber/10 text-fg" : "border-white/[0.08] text-fg-3 hover:text-fg",
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
      </PageHeader>
      <div className="px-8 py-7">{current && <FileBrowser root={current} />}</div>
    </>
  );
}
