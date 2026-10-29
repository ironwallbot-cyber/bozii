"use client";

import { useState } from "react";
import Link from "next/link";
import {
  FileText,
  FileArchive,
  Image,
  Code,
  Download,
  ExternalLink,
  Clock,
  Trash2,
  File,
} from "lucide-react";
import { PageHeader } from "@/components/shell";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Input,
  Loading,
} from "@/components/ui";
import { Search } from "lucide-react";
import { del, errorMessage, get } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Artifact } from "@/lib/types";
import { bytes, formatDate, relativeTime } from "@/lib/format";

const KIND_LABELS: Record<string, string> = {
  report: "report",
  file: "file",
  code: "code",
  archive: "archive",
  image: "image",
  data: "data",
  plan: "plan",
  log: "log",
  other: "other",
};

function kindIcon(kind: string) {
  if (kind === "report" || kind === "plan") return <FileText size={15} className="text-muted" />;
  if (kind === "archive") return <FileArchive size={15} className="text-muted" />;
  if (kind === "image") return <Image size={15} className="text-muted" />;
  if (kind === "code") return <Code size={15} className="text-muted" />;
  return <File size={15} className="text-muted" />;
}

export default function ArtifactsPage() {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const artifacts = useApi<Artifact[]>("/api/artifacts", 3000);

  const q = query.trim().toLowerCase();
  const filtered =
    artifacts.data?.filter(
      (a) =>
        (!kind || a.kind === kind) &&
        (!q ||
          a.name.toLowerCase().includes(q) ||
          a.kind.toLowerCase().includes(q) ||
          a.relative_path.toLowerCase().includes(q)),
    ) ?? [];

  const byKind = (items: Artifact[]) =>
    items.reduce<Record<string, Artifact[]>>((acc, a) => {
      (acc[a.kind] ??= []).push(a);
      return acc;
    }, {});

  return (
    <div className="reveal">
      <PageHeader
        title="Artifacts"
        description="Files, reports, code and exports produced by your employees."
        action={
          <div className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5">
            <Search size={14} className="text-muted" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search artifacts"
              className="w-40 bg-transparent text-sm outline-none sm:w-56"
            />
          </div>
        }
      />

      {artifacts.error ? (
        <ErrorNote message={artifacts.error} />
      ) : artifacts.loading && !artifacts.data ? (
        <Loading label="Loading artifacts…" />
      ) : filtered.length === 0 ? (
        <EmptyState
          title="No artifacts yet"
          description="Artifacts appear here once an employee produces a file, report, or export."
        />
      ) : (
        <div className="space-y-6">
          {Object.entries(byKind(filtered))
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([kindLabel, items]) => (
              <Card key={kindLabel} padded={false}>
                <div className="flex items-center justify-between border-b border-line px-4 py-3">
                  <h2 className="text-sm font-semibold capitalize">
                    {kindLabel} · {items.length}
                  </h2>
                  <span className="text-xs text-muted">{kindLabel}</span>
                </div>
                <ul className="divide-y divide-line">
                  {items.map((artifact) => (
                    <li key={artifact.id} className="flex items-center justify-between gap-3 px-4 py-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          {kindIcon(artifact.kind)}
                          <span className="truncate text-sm font-medium">{artifact.name}</span>
                          <Badge>{KIND_LABELS[artifact.kind] ?? artifact.kind}</Badge>
                          {artifact.sha256 ? (
                            <span className="text-[11px] font-mono text-faint">
                              {artifact.sha256.slice(0, 8)}
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-0.5 text-xs text-muted truncate">{artifact.relative_path}</p>
                      </div>
                      <div className="flex items-center gap-3 shrink-0">
                        <span className="text-xs text-muted">{bytes(artifact.size)}</span>
                        <span className="text-xs text-muted">{relativeTime(artifact.created_at)}</span>
                        {artifact.task_id ? (
                          <Link
                            href={`/tasks/${artifact.task_id}`}
                            className="text-xs text-accent hover:underline"
                          >
                            Task {artifact.task_id.slice(0, 8)}
                          </Link>
                        ) : null}
                        <a
                          href={`/api/artifacts/${artifact.id}/download`}
                          className="rounded-lg border border-line px-2.5 py-1 text-xs text-ink-2 hover:bg-surface-2"
                        >
                          <Download size={13} className="inline mr-1" />
                          Download
                        </a>
                      </div>
                    </li>
                  ))}
                </ul>
              </Card>
            ))}
        </div>
      )}
    </div>
  );
}
