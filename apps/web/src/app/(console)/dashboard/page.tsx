"use client";

import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  Package,
  Play,
  ShieldAlert,
  Wrench,
} from "lucide-react";
import { PageHeader } from "@/components/shell";
import { Badge, Button, Card, EmptyState, KeyValue, Loading, SectionTitle, StatTile } from "@/components/ui";
import { useApi, useSSE } from "@/lib/hooks";
import type { ActivityItem, Artifact, AppSettings, DashboardStats, Task } from "@/lib/types";
import { bytes, relativeTime } from "@/lib/format";

export default function DashboardPage() {
  const stats = useApi<DashboardStats>("/api/dashboard", 5000);
  const activity = useApi<ActivityItem[]>("/api/activity?limit=14", 6000);
  const artifacts = useApi<Artifact[]>("/api/artifacts?limit=6", 8000);
  const waiting = useApi<Task[]>("/api/tasks?state=waiting_approval", 4000);
  const settings = useApi<AppSettings>("/api/settings", 0);

  useSSE(["activity"], () => {
    stats.refetch();
    activity.refetch();
    waiting.refetch();
  });

  if (stats.loading && !stats.data) return <Loading label="Loading dashboard…" />;

  const data = stats.data;
  const providersMissing = data ? data.providers_total === 0 : false;

  return (
    <div className="reveal">
      <PageHeader
        title="Dashboard"
        description="Every number below is computed from live application data."
        action={
          <Link href="/tasks?new=1">
            <Button variant="primary">
              New task <ArrowRight size={15} />
            </Button>
          </Link>
        }
      />

      {providersMissing ? (
        <div className="mb-5 rounded-xl border border-amber-200 bg-warning-soft px-4 py-3 text-sm text-warning">
          No model provider is configured, so tasks cannot run yet.{" "}
          <Link href="/settings" className="font-medium underline">
            Add Ollama or an OpenAI-compatible endpoint →
          </Link>
        </div>
      ) : null}

      {waiting.data && waiting.data.length > 0 ? (
        <div className="mb-5 rounded-xl border border-amber-200 bg-warning-soft px-4 py-3 text-sm text-warning">
          <span className="flex items-center gap-2">
            <ShieldAlert size={15} />
            {waiting.data.length} task{waiting.data.length === 1 ? "" : "s"} waiting for your approval.{" "}
            <Link href={`/tasks/${waiting.data[0].id}`} className="font-medium underline">
              Review →
            </Link>
          </span>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatTile label="Employees" value={data?.employees ?? 0} />
        <StatTile
          label="Active"
          value={data?.active_tasks ?? 0}
          tone={(data?.active_tasks ?? 0) > 0 ? "accent" : "neutral"}
        />
        <StatTile label="Queued" value={data?.queued_tasks ?? 0} />
        <StatTile label="Completed" value={data?.completed_tasks ?? 0} tone="success" />
        <StatTile label="Failed" value={data?.failed_tasks ?? 0} tone={(data?.failed_tasks ?? 0) > 0 ? "danger" : "neutral"} />
        <StatTile
          label="Waiting approval"
          value={data?.waiting_approval ?? 0}
          tone={(data?.waiting_approval ?? 0) > 0 ? "warning" : "neutral"}
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        {/* --------------------------------------------------- providers */}
        <Card>
          <SectionTitle
            title="Model providers"
            subtitle={
              data
                ? `${data.providers_ok}/${data.providers_total} healthy · ${data.tools} tools available`
                : "—"
            }
            action={
              <Link href="/settings">
                <Button size="sm" variant="quiet">
                  Manage
                </Button>
              </Link>
            }
          />
          <div className="space-y-2 text-sm">
            <KeyValue label="Tokens used (all time)" value={(data?.tokens_used ?? 0).toLocaleString()} />
            <KeyValue label="Tasks (last 7 days)" value={data?.tasks_last_7d ?? 0} />
            <KeyValue label="Capabilities" value={`${data?.capabilities ?? 0} (${data?.public_capabilities ?? 0} public)`} />
            <KeyValue label="Artifacts" value={data?.artifacts ?? 0} />
            <KeyValue
              label="Execution sandbox"
              value={
                settings.data ? (
                  <span className="inline-flex flex-wrap items-center justify-end gap-1">
                    <Badge tone={settings.data.sandbox.network_isolation ? "success" : "warning"}>
                      {settings.data.sandbox.network_isolation ? "net-isolated" : "shared network"}
                    </Badge>
                    <Badge tone={settings.data.sandbox.privilege_drop ? "success" : "neutral"}>
                      {settings.data.sandbox.privilege_drop ? "unprivileged" : "no priv-drop"}
                    </Badge>
                  </span>
                ) : (
                  "—"
                )
              }
            />
          </div>
        </Card>

        {/* ---------------------------------------------------- activity */}
        <Card>
          <SectionTitle
            title="Recent activity"
            subtitle="Audit trail and task events, newest first"
            action={
              <Link href="/activity">
                <Button size="sm" variant="quiet">
                  View all
                </Button>
              </Link>
            }
          />
          {activity.loading && !activity.data ? (
            <Loading />
          ) : activity.data && activity.data.length > 0 ? (
            <ul className="space-y-2.5">
              {activity.data.slice(0, 8).map((item) => (
                <li key={item.id} className="flex items-start gap-2.5 text-sm">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-line-strong" />
                  <div className="min-w-0">
                    <p className="truncate text-ink-2">{item.message}</p>
                    <p className="text-xs text-muted">
                      {item.action} · {relativeTime(item.created_at)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No activity yet" description="Actions performed in the console and by employees will appear here." />
          )}
        </Card>

        {/* -------------------------------------------------- artifacts */}
        <Card>
          <SectionTitle
            title="Latest deliverables"
            subtitle="Generated by employees"
            action={
              <Link href="/artifacts">
                <Button size="sm" variant="quiet">
                  All artifacts
                </Button>
              </Link>
            }
          />
          {artifacts.loading && !artifacts.data ? (
            <Loading />
          ) : artifacts.data && artifacts.data.length > 0 ? (
            <ul className="divide-y divide-line">
              {artifacts.data.slice(0, 6).map((artifact) => (
                <li key={artifact.id} className="flex items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{artifact.name}</p>
                    <p className="text-xs text-muted">
                      {artifact.kind} · {bytes(artifact.size)} · {relativeTime(artifact.created_at)}
                    </p>
                  </div>
                  <a
                    href={`/api/artifacts/${artifact.id}/download`}
                    className="shrink-0 rounded-lg border border-line px-2.5 py-1.5 text-xs text-ink-2 hover:bg-surface-2"
                  >
                    Download
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No artifacts yet"
              description="Deliverables created by employees during tasks show up here for download."
            />
          )}
        </Card>
      </div>

      {/* ------------------------------------------------------ task strip */}
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card>
          <SectionTitle title="Execution states" subtitle="Live counts across every task" />
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2">
              <Play size={14} className="text-accent" /> Running
              <span className="ml-auto font-medium tabular-nums">{data?.active_tasks ?? 0}</span>
            </div>
            <div className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2">
              <Clock3 size={14} className="text-info" /> Queued
              <span className="ml-auto font-medium tabular-nums">{data?.queued_tasks ?? 0}</span>
            </div>
            <div className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2">
              <CheckCircle2 size={14} className="text-success" /> Done
              <span className="ml-auto font-medium tabular-nums">{data?.completed_tasks ?? 0}</span>
            </div>
            <div className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2">
              <AlertTriangle size={14} className="text-danger" /> Failed
              <span className="ml-auto font-medium tabular-nums">{data?.failed_tasks ?? 0}</span>
            </div>
          </div>
        </Card>

        <Card className="lg:col-span-2">
          <SectionTitle
            title="Quick actions"
            subtitle="Common starting points"
          />
          <div className="grid gap-2 sm:grid-cols-2">
            {[
              { href: "/employees?new=1", label: "Hire an employee", icon: Wrench, note: "Start from a template or build your own" },
              { href: "/tasks?new=1", label: "Assign a task", icon: Play, note: "Delegate an objective to an employee" },
              { href: "/library?new=1", label: "Create a capability", icon: Package, note: "Validated in a sandbox before activation" },
              { href: "/settings", label: "Connect a free model", icon: ShieldAlert, note: "Ollama or any OpenAI-compatible endpoint" },
            ].map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className="flex items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 transition-colors hover:bg-surface-2"
                >
                  <Icon size={16} className="text-accent" />
                  <div>
                    <p className="text-sm font-medium">{item.label}</p>
                    <p className="text-xs text-muted">{item.note}</p>
                  </div>
                  <ArrowRight size={14} className="ml-auto text-faint" />
                </Link>
              );
            })}
          </div>
        </Card>
      </div>
    </div>
  );
}
