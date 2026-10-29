"use client";

import { use, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  Check,
  Clock3,
  Download,
  FileText,
  GitBranch,
  Pause,
  Play,
  RotateCcw,
  ShieldQuestion,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNote,
  KeyValue,
  Loading,
  Notice,
  SectionTitle,
  StateBadge,
} from "@/components/ui";
import { errorMessage, get, post } from "@/lib/api";
import { useApi, useSSE } from "@/lib/hooks";
import type { TaskDetail, TaskEvent } from "@/lib/types";
import { bytes, formatDate, relativeTime } from "@/lib/format";

const EVENT_ICONS: Record<string, string> = {
  state_change: "bg-info",
  planned: "bg-info",
  tool_call: "bg-line-strong",
  tool_result: "bg-accent",
  error: "bg-danger",
  approval: "bg-warning",
  artifact: "bg-success",
  delegated: "bg-warning",
  capability: "bg-accent",
  message: "bg-line-strong",
};

function Controls({ task, onRefresh }: { task: TaskDetail; onRefresh: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const act = async (action: string) => {
    setBusy(true);
    setError(null);
    try {
      await post(`/api/tasks/${task.id}/${action}`, action === "approve" ? undefined : {});
      onRefresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const active = ["queued", "planning", "running", "recovering"].includes(task.state);
  const terminal = ["completed", "failed", "cancelled"].includes(task.state);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {error ? <ErrorNote message={error} /> : null}
      {active ? (
        <>
          <Button size="sm" onClick={() => act("pause")} disabled={busy}>
            <Pause size={14} /> Pause
          </Button>
          <Button size="sm" variant="quiet" onClick={() => act("cancel")} disabled={busy}>
            <Ban size={14} /> Cancel
          </Button>
        </>
      ) : null}
      {task.state === "paused" ? (
        <Button size="sm" variant="primary" onClick={() => act("resume")} disabled={busy}>
          <Play size={14} /> Resume
        </Button>
      ) : null}
      {terminal ? (
        <Button size="sm" variant="secondary" onClick={() => act("retry")} disabled={busy}>
          <RotateCcw size={14} /> Retry
        </Button>
      ) : null}
    </div>
  );
}

function Approvals({ task, onRefresh }: { task: TaskDetail; onRefresh: () => void }) {
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const pending = task.approvals.filter((approval) => approval.state === "pending");

  const decide = async (approve: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await post(`/api/tasks/${task.id}/approve`, { approve, reason: reason.trim() });
      setReason("");
      onRefresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  if (pending.length === 0) {
    const decided = task.approvals.slice(0, 3);
    if (decided.length === 0) return null;
    return (
      <Card className="mb-4">
        <SectionTitle title="Approval history" />
        <ul className="space-y-2 text-sm">
          {decided.map((approval) => (
            <li key={approval.id} className="flex items-center justify-between gap-3">
              <span className="truncate text-ink-2">{approval.title}</span>
              <Badge tone={approval.state === "approved" ? "success" : "danger"}>{approval.state}</Badge>
            </li>
          ))}
        </ul>
      </Card>
    );
  }

  return (
    <div className="mb-4 space-y-3">
      {pending.map((approval) => (
        <div key={approval.id} className="rounded-xl border border-amber-200 bg-warning-soft p-4">
          <div className="flex items-start gap-3">
            <ShieldQuestion size={17} className="mt-0.5 shrink-0 text-warning" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-warning">Approval required</p>
              <p className="mt-0.5 whitespace-pre-wrap text-sm text-ink-2">{approval.description}</p>
              <p className="mt-1 text-xs text-muted">
                Requested {relativeTime(approval.created_at)} · executing continues only after you decide.
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => decide(true)}
                  disabled={busy}
                >
                  <Check size={14} /> Approve
                </Button>
                <Button size="sm" variant="secondary" onClick={() => decide(false)} disabled={busy}>
                  <X size={14} /> Deny
                </Button>
                <input
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Reason (optional)"
                  className="ml-1 w-52 rounded-lg border border-amber-200 bg-white px-3 py-1.5 text-sm outline-none focus:border-warning"
                />
              </div>
              {error ? <div className="mt-2"><ErrorNote message={error} /></div> : null}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function TaskDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const task = useApi<TaskDetail>(`/api/tasks/${id}`, 2500);
  const [tab, setTab] = useState<"timeline" | "conversation">("timeline");

  useSSE([`task:${id}`], (event) => {
    if (event.type === "task_event" || event.type === "activity") task.refetch();
  });

  if (task.loading && !task.data) return <Loading label="Loading task…" />;
  if (!task.data) return <ErrorNote message={task.error ?? "Task not found"} />;

  const detail = task.data;
  const events: TaskEvent[] = detail.events ?? [];

  return (
    <div className="reveal">
      <Link
        href="/tasks"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink"
      >
        <ArrowLeft size={14} /> All tasks
      </Link>

      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">{detail.title}</h1>
            <StateBadge state={detail.state} />
            {detail.attempt > 1 ? <Badge tone="warning">attempt {detail.attempt}</Badge> : null}
          </div>
          <p className="mt-1 text-sm text-muted">
            Assigned to{" "}
            <Link href={`/employees/${detail.employee_id}`} className="text-accent hover:underline">
              {detail.employee_name || "employee"}
            </Link>{" "}
            · created {relativeTime(detail.created_at)}
            {detail.started_at ? ` · started ${formatDate(detail.started_at)}` : ""}
            {detail.finished_at ? ` · finished ${formatDate(detail.finished_at)}` : ""}
          </p>
          <p className="mt-1 text-xs text-faint">
            {detail.iterations_used}/{detail.max_iterations} iterations · {detail.tool_calls} tool calls ·
            timeout {Math.round(detail.max_iterations > 0 ? (detail.max_iterations * 30) / 60 : 0)} min
          </p>
        </div>
        <Controls task={detail} onRefresh={task.refetch} />
      </div>

      {detail.error ? (
        <div className="mb-4">
          <ErrorNote message={detail.error} />
        </div>
      ) : null}
      {detail.state === "paused" ? (
        <div className="mb-4">
          <Notice message="This task is paused. Resume it to continue from where it stopped." tone="warning" />
        </div>
      ) : null}

      <Approvals task={detail} onRefresh={task.refetch} />

      <div className="grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
        {/* --------------------------------------------------- left column */}
        <div className="space-y-4">
          <Card>
            <SectionTitle title="Objective" />
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-2">{detail.objective}</p>
          </Card>

          {detail.plan.length > 0 ? (
            <Card>
              <SectionTitle
                title="Plan"
                subtitle="Steps reported by the employee as it works — not fabricated progress."
              />
              <ol className="space-y-3">
                {detail.plan.map((step, index) => {
                  const subtask = detail.subtasks[index];
                  const status = subtask?.status ?? step.status ?? "pending";
                  return (
                    <li key={index} className="flex gap-3">
                      <span
                        className={`mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                          status === "done"
                            ? "bg-success text-white"
                            : status === "failed"
                              ? "bg-danger text-white"
                              : status === "running"
                                ? "bg-accent text-white"
                                : "bg-surface-2 text-muted"
                        }`}
                      >
                        {index + 1}
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm font-medium">{step.title}</p>
                        <p className="text-xs text-muted">{step.description}</p>
                        {subtask?.output ? (
                          <p className="mt-1 rounded-lg bg-surface-2 px-2 py-1 text-xs text-ink-2">
                            {subtask.output}
                          </p>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
              </ol>
            </Card>
          ) : null}

          {detail.artifacts.length > 0 ? (
            <Card>
              <SectionTitle title="Artifacts" subtitle={`${detail.artifacts.length} deliverable(s)`} />
              <ul className="divide-y divide-line">
                {detail.artifacts.map((artifact) => (
                  <li key={artifact.id} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <FileText size={15} className="shrink-0 text-muted" />
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">{artifact.name}</p>
                        <p className="text-xs text-muted">
                          {artifact.kind} · {bytes(artifact.size)} · {formatDate(artifact.created_at)}
                        </p>
                      </div>
                    </div>
                    <a
                      href={`/api/artifacts/${artifact.id}/download`}
                      className="shrink-0 rounded-lg border border-line px-2.5 py-1.5 text-xs text-ink-2 hover:bg-surface-2"
                    >
                      <Download size={13} className="mr-1 inline" />
                      Get
                    </a>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          {null}
          <ChildrenCard taskId={detail.id} />

          {detail.report ? (
            <Card>
              <SectionTitle title="Final report" subtitle="Produced by the employee after execution." />
              <div className="max-h-[420px] overflow-y-auto whitespace-pre-wrap rounded-lg bg-surface-2 p-4 text-sm leading-relaxed text-ink-2">
                {detail.report}
              </div>
            </Card>
          ) : detail.state === "completed" ? (
            <Card>
              <Notice message="The task completed without a written report; inspect the event log for what ran." />
            </Card>
          ) : null}
        </div>

        {/* -------------------------------------------------- right column */}
        <div className="space-y-4">
          <Card padded={false}>
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div className="flex gap-1">
                <button
                  onClick={() => setTab("timeline")}
                  className={`rounded-lg px-3 py-1.5 text-sm ${
                    tab === "timeline" ? "bg-surface-2 font-medium text-ink" : "text-muted hover:text-ink"
                  }`}
                >
                  Execution log
                </button>
                <button
                  onClick={() => setTab("conversation")}
                  className={`rounded-lg px-3 py-1.5 text-sm ${
                    tab === "conversation"
                      ? "bg-surface-2 font-medium text-ink"
                      : "text-muted hover:text-ink"
                  }`}
                >
                  Messages
                </button>
              </div>
              <span className="flex items-center gap-1.5 text-xs text-muted">
                <span className="pulse-dot" /> live
              </span>
            </div>

            <div className="max-h-[640px] overflow-y-auto">
              {tab === "timeline" ? (
                events.length > 0 ? (
                  <ol className="divide-y divide-line">
                    {events.map((event) => (
                      <li key={event.id} className="flex gap-3 px-4 py-2.5">
                        <span className="log-row w-8 shrink-0 pt-0.5 text-faint">#{event.seq}</span>
                        <span
                          className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                            EVENT_ICONS[event.type] ?? "bg-line-strong"
                          }`}
                        />
                        <div className="min-w-0 flex-1">
                          <p className="log-row break-words text-ink-2">{event.message}</p>
                          {event.payload && Object.keys(event.payload).length > 0 ? (
                            <details className="mt-1">
                              <summary className="cursor-pointer text-[11px] text-faint">
                                details
                              </summary>
                              <pre className="log-row mt-1 overflow-x-auto whitespace-pre-wrap rounded bg-surface-2 p-2 text-muted">
                                {JSON.stringify(event.payload, null, 2)}
                              </pre>
                            </details>
                          ) : null}
                        </div>
                        <span className="log-row shrink-0 text-faint">{formatDate(event.created_at)}</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <EmptyState
                    title="No events yet"
                    description="State changes, tool calls and results stream here as they happen."
                  />
                )
              ) : detail.messages.length > 0 ? (
                <ol className="divide-y divide-line">
                  {detail.messages.map((message, index) => (
                    <li key={index} className="px-4 py-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold uppercase tracking-wider text-muted">
                          {message.role}
                          {message.name ? ` · ${message.name}` : ""}
                          {message.tool_call_id ? ` · ${message.tool_call_id}` : ""}
                        </span>
                      </div>
                      <p className="log-row mt-1.5 max-h-64 overflow-y-auto whitespace-pre-wrap break-words text-ink-2">
                        {message.content || "(tool call)"}
                      </p>
                      {message.tool_calls?.length ? (
                        <pre className="log-row mt-1.5 overflow-x-auto rounded bg-surface-2 p-2 text-muted">
                          {message.tool_calls
                            .map((call) => `${call.function.name}(${call.function.arguments})`)
                            .join("\n")}
                        </pre>
                      ) : null}
                    </li>
                  ))}
                </ol>
              ) : (
                <EmptyState
                  title="No conversation yet"
                  description="The full message history — including tool calls and results — appears here."
                />
              )}
            </div>
          </Card>

          <Card>
            <SectionTitle title="Task facts" />
            <div className="grid gap-x-6 sm:grid-cols-2">
              <KeyValue label="State" value={<StateBadge state={detail.state} />} />
              <KeyValue label="Attempt" value={detail.attempt} />
              <KeyValue label="Iterations" value={`${detail.iterations_used}/${detail.max_iterations}`} />
              <KeyValue label="Tool calls" value={detail.tool_calls} />
              <KeyValue label="Priority" value={detail.priority} />
              <KeyValue label="Delegation depth" value={detail.delegation_depth} />
              <KeyValue label="Task id" value={<span className="log-row">{detail.id.slice(0, 12)}…</span>} />
              <KeyValue
                label="Updated"
                value={detail.updated_at ? relativeTime(detail.updated_at) : "—"}
              />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function ChildrenCard({ taskId }: { taskId: string }) {
  const children = useApi<{ id: string; title: string; state: string; updated_at: string }[]>(
    `/api/tasks/${taskId}/children`,
    4000,
  );
  if (!children.data || children.data.length === 0) return null;
  return (
    <Card>
      <SectionTitle
        title="Delegated subtasks"
        subtitle="Child tasks this employee assigned to others."
      />
      <ul className="divide-y divide-line">
        {children.data.map((child) => (
          <li key={child.id}>
            <Link
              href={`/tasks/${child.id}`}
              className="flex items-center justify-between gap-3 py-2.5 hover:bg-surface-2"
            >
              <span className="flex min-w-0 items-center gap-2 text-sm">
                <GitBranch size={14} className="shrink-0 text-muted" />
                <span className="truncate">{child.title}</span>
              </span>
              <StateBadge state={child.state} />
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}
