"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Clock, User, FileText, GitBranch, Shield, AlertTriangle, CheckCircle, XCircle, Mail } from "lucide-react";
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
import { get } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { ActivityItem } from "@/lib/types";
import { formatDate, relativeTime } from "@/lib/format";

const SOURCE_LABELS: Record<string, string> = {
  audit: "Platform event",
  task_event: "Task event",
};

function sourceIcon(source: string) {
  if (source === "audit") return <Shield size={14} className="text-muted" />;
  return <FileText size={14} className="text-muted" />;
}

function actionBadge(action: string, detail?: Record<string, unknown>) {
  const lower = action.toLowerCase();
  if (lower.startsWith("task.") || lower.startsWith("capability.")) {
    return <Badge>{action}</Badge>;
  }
  return null;
}

function ActorChip({ actor }: { actor: string }) {
  if (actor.startsWith("employee:")) {
    const id = actor.slice("employee:".length);
    return (
      <span className="rounded-full border border-line bg-surface-2 px-2 py-0.5 text-xs text-ink-2">
        employee {id.slice(0, 8)}
      </span>
    );
  }
  if (actor.startsWith("user:")) {
    const id = actor.slice("user:".length);
    return (
      <span className="rounded-full border border-line bg-surface-2 px-2 py-0.5 text-xs text-ink-2">
        user {id.slice(0, 8)}
      </span>
    );
  }
  return <span className="text-xs text-muted">{actor}</span>;
}

const ACTIVITY_ICONS: Record<string, string> = {
  success: "bg-success",
  info: "bg-info",
  warning: "bg-warning",
  error: "bg-danger",
};

export default function ActivityPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [query, setQuery] = useState("");
  const [source, setSource] = useState<string>(
    params.get("source") ?? "all",
  );
  const activities = useApi<ActivityItem[]>("/api/activity", 3000);

  const q = query.trim().toLowerCase();
  const filtered =
    activities.data?.filter((a) => {
      if (source !== "all" && a.source !== source) return false;
      if (
        !q ||
        a.message.toLowerCase().includes(q) ||
        a.action.toLowerCase().includes(q) ||
        a.actor.toLowerCase().includes(q) ||
        a.resource_type.toLowerCase().includes(q)
      ) {
        return true;
      }
      return false;
    }) ?? [];

  const bySource = (items: ActivityItem[]) =>
    items.reduce<Record<string, ActivityItem[]>>((acc, a) => {
      (acc[a.source] ??= []).push(a);
      return acc;
    }, {});

  return (
    <div className="reveal">
      <PageHeader
        title="Activity"
        description="A chronological record of what happened in your Bozii workspace."
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5">
          <Search size={14} className="text-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search activity"
            className="w-40 bg-transparent text-sm outline-none sm:w-56"
          />
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setSource("all")}
            className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
              source === "all"
                ? "border-graphite bg-graphite text-white"
                : "border-line bg-surface text-ink-2 hover:bg-surface-2"
            }`}
          >
            All
          </button>
          <button
            onClick={() => setSource("audit")}
            className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
              source === "audit"
                ? "border-graphite bg-graphite text-white"
                : "border-line bg-surface text-ink-2 hover:bg-surface-2"
            }`}
          >
            Platform
          </button>
          <button
            onClick={() => setSource("task_event")}
            className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
              source === "task_event"
                ? "border-graphite bg-graphite text-white"
                : "border-line bg-surface text-ink-2 hover:bg-surface-2"
            }`}
          >
            Task events
          </button>
        </div>
      </div>

      {activities.error ? (
        <ErrorNote message={activities.error} />
      ) : activities.loading && !activities.data ? (
        <Loading label="Loading activity…" />
      ) : filtered.length === 0 ? (
        <EmptyState
          title="No activity yet"
          description="Platform and task events will appear here once something happens in your workspace."
        />
      ) : (
        <div className="space-y-5">
          {Object.entries(bySource(filtered))
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([sourceKey, items]) => (
              <Card key={sourceKey} padded={false}>
                <div className="flex items-center justify-between border-b border-line px-4 py-3">
                  <h2 className="text-sm font-semibold capitalize">
                    {SOURCE_LABELS[sourceKey] ?? sourceKey}
                  </h2>
                  <span className="text-xs text-muted">{items.length} events</span>
                </div>
                <ul className="divide-y divide-line">
                  {items.map((item) => {
                    const icon =
                      item.action.startsWith("task.failed") ||
                      item.action.startsWith("capability.failed")
                        ? "error"
                        : item.action.startsWith("task.completed") ||
                          item.action.startsWith("capability.active")
                        ? "success"
                        : item.action.startsWith("task.planning") ||
                          item.action.startsWith("task.delegated")
                        ? "info"
                        : item.action.startsWith("approval") ||
                          item.action.startsWith("task.waiting")
                        ? "warning"
                        : "info";

                    return (
                      <li key={item.id} className="flex gap-3 px-4 py-3">
                        <div className={`mt-1 shrink-0 rounded-full bg-surface-2 p-1 ${ACTIVITY_ICONS[icon] ?? "bg-info"}`}>
                          {sourceIcon(item.source)}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            {actionBadge(item.action, item.detail)}
                            <span className="text-sm text-ink-2">{item.message}</span>
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                            <ActorChip actor={item.actor} />
                            {item.resource_type ? (
                              <span className="text-faint">· {item.resource_type} {item.resource_id?.slice(0, 8)}</span>
                            ) : null}
                            <span>· {relativeTime(item.created_at)}</span>
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </Card>
            ))}
        </div>
      )}
    </div>
  );
}
