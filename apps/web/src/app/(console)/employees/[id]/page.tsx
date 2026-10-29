"use client";

import { FormEvent, use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Brain,
  CheckCircle2,
  MemoryStick,
  Play,
  Settings2,
  Terminal,
  Trash2,
  Wrench,
} from "lucide-react";
import {
  Avatar,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Field,
  Input,
  KeyValue,
  Loading,
  Notice,
  SectionTitle,
  Select,
  StateBadge,
  Tabs,
  Textarea,
  Toggle,
} from "@/components/ui";
import { del, errorMessage, get, patch, post } from "@/lib/api";
import { useApi, useSSE } from "@/lib/hooks";
import type { Capability, Employee, EmployeeTemplate, MemoryEntry, ModelInfo, Task, TaskEvent } from "@/lib/types";
import { colorFor, formatDate, relativeTime } from "@/lib/format";

type TabKey = "workspace" | "memory" | "tools" | "settings" | "capabilities";

const PERMISSION_HELP: Record<string, { label: string; options: [string, string][] }> = {
  fs: {
    label: "Filesystem",
    options: [
      ["none", "No file access"],
      ["workspace", "Own workspace only"],
    ],
  },
  net: {
    label: "Network",
    options: [
      ["none", "No network"],
      ["search", "Web search only"],
      ["fetch", "Search and fetch pages"],
    ],
  },
  exec: {
    label: "Command execution",
    options: [
      ["none", "No commands"],
      ["sandbox", "Sandboxed, allow-listed"],
    ],
  },
};

export default function EmployeeDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const employee = useApi<Employee>(`/api/employees/${id}`, 0);
  const tasks = useApi<Task[]>(`/api/employees/${id}/tasks`, 4000);
  const timeline = useApi<TaskEvent[]>(`/api/employees/${id}/timeline`, 5000);
  const memory = useApi<MemoryEntry[]>(`/api/employees/${id}/memory`, 8000);
  const capabilities = useApi<Capability[]>(`/api/employees/${id}/capabilities`, 8000);
  const models = useApi<ModelInfo[]>("/api/models", 0);

  const [tab, setTab] = useState<TabKey>("workspace");
  const [objective, setObjective] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Settings form state
  const [form, setForm] = useState<Partial<Employee> | null>(null);
  const [saving, setSaving] = useState(false);

  // Memory form
  const [memoryKey, setMemoryKey] = useState("");
  const [memoryContent, setMemoryContent] = useState("");

  useEffect(() => {
    if (employee.data && !form) setForm(employee.data);
  }, [employee.data, form]);

  useSSE(["activity"], () => {
    tasks.refetch();
    timeline.refetch();
  });

  if (employee.loading && !employee.data) return <Loading label="Loading employee…" />;
  if (!employee.data || !form) {
    return <ErrorNote message={employee.error ?? "Employee not found"} />;
  }

  const person = employee.data;

  const assign = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const task = await post<Task>("/api/tasks", {
        employee_id: person.id,
        objective: objective.trim(),
      });
      setObjective("");
      tasks.refetch();
      router.push(`/tasks/${task.id}`);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const saveSettings = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await patch<Employee>(`/api/employees/${id}`, {
        name: form.name,
        role: form.role,
        description: form.description,
        system_prompt: form.system_prompt,
        model_id: form.model_id,
        temperature: form.temperature,
        max_iterations: form.max_iterations,
        timeout_seconds: form.timeout_seconds,
        memory_enabled: form.memory_enabled,
        permissions: form.permissions,
        status: form.status,
      });
      setForm(updated);
      employee.refetch();
      setNotice("Saved.");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSaving(false);
    }
  };

  const setPermission = (key: string, value: string) => {
    setForm({
      ...form,
      permissions: { ...(form.permissions ?? {}), [key]: value },
    });
  };

  const addMemory = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await post(`/api/employees/${id}/memory`, {
        kind: "fact",
        key: memoryKey.trim(),
        content: memoryContent.trim(),
      });
      setMemoryKey("");
      setMemoryContent("");
      memory.refetch();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  const removeMemory = async (memoryId: string) => {
    try {
      await del(`/api/employees/${id}/memory/${memoryId}`);
      memory.refetch();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  const tabs: { key: TabKey; label: string; count?: number }[] = [
    { key: "workspace", label: "Workspace" },
    { key: "memory", label: "Memory", count: memory.data?.length },
    { key: "tools", label: "Permissions" },
    { key: "capabilities", label: "Capabilities", count: capabilities.data?.length },
    { key: "settings", label: "Settings" },
  ];

  return (
    <div className="reveal">
      <Link
        href="/employees"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink"
      >
        <ArrowLeft size={14} /> All employees
      </Link>

      <div className="mb-5 flex flex-wrap items-start gap-4">
        <Avatar
          name={person.name}
          color={person.avatar_color || colorFor(person.id)}
          size={52}
          seed={person.avatar_seed}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">{person.name}</h1>
            <Badge tone={person.status === "active" ? "success" : "neutral"}>{person.status}</Badge>
            {person.model_name ? <Badge>{person.model_name}</Badge> : null}
          </div>
          <p className="mt-0.5 text-sm text-muted">
            {person.role} · {person.description || "No description"}
          </p>
          <p className="mt-1 text-xs text-faint">
            {person.completed_tasks} completed · {person.active_tasks} active · {person.failed_tasks} failed ·
            created {relativeTime(person.created_at)}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={async () => {
              const next = person.status === "active" ? "paused" : "active";
              const updated = await patch<Employee>(`/api/employees/${id}`, { status: next });
              setForm(updated);
              employee.refetch();
            }}
          >
            {person.status === "active" ? "Pause employee" : "Activate employee"}
          </Button>
          <Button
            variant="quiet"
            size="sm"
            onClick={async () => {
              if (!window.confirm("Delete this employee? This cannot be undone.")) return;
              await del(`/api/employees/${id}`);
              router.push("/employees");
            }}
          >
            <Trash2 size={14} />
          </Button>
        </div>
      </div>

      <Tabs tabs={tabs} active={tab} onChange={(key) => setTab(key as TabKey)} />

      <div className="mt-5">
        {error ? <div className="mb-4"><ErrorNote message={error} /></div> : null}
        {notice ? <div className="mb-4"><Notice message={notice} /></div> : null}

        {/* ------------------------------------------------------ workspace */}
        {tab === "workspace" ? (
          <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
            <Card>
              <SectionTitle
                title="Assign a task"
                subtitle="The employee plans, executes and reports back with artifacts."
              />
              <form onSubmit={assign} className="space-y-3">
                <Textarea
                  rows={5}
                  value={objective}
                  onChange={(event) => setObjective(event.target.value)}
                  placeholder="Example: Research the three most-used open-source agent frameworks, compare their licensing, and write a sourced comparison report into the workspace."
                  required
                />
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs text-muted">
                    Up to {person.max_iterations} iterations · {Math.round(person.timeout_seconds / 60)} min budget
                  </span>
                  <Button type="submit" variant="primary" disabled={busy || !objective.trim()}>
                    <Play size={15} /> Assign task
                  </Button>
                </div>
              </form>

              <div className="mt-5 border-t border-line pt-4">
                <SectionTitle title="Recent tasks" />
                {tasks.data && tasks.data.length > 0 ? (
                  <ul className="divide-y divide-line">
                    {tasks.data.slice(0, 8).map((task) => (
                      <li key={task.id}>
                        <Link
                          href={`/tasks/${task.id}`}
                          className="flex items-center justify-between gap-3 py-2.5 hover:bg-surface-2"
                        >
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium">{task.title}</p>
                            <p className="text-xs text-muted">{relativeTime(task.created_at)}</p>
                          </div>
                          <StateBadge state={task.state} />
                        </Link>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState
                    title="No tasks yet"
                    description="Assign the first objective to this employee."
                  />
                )}
              </div>
            </Card>

            <Card>
              <SectionTitle
                title="Execution timeline"
                subtitle="Live tool calls, state changes and errors"
              />
              {timeline.data && timeline.data.length > 0 ? (
                <ol className="space-y-3">
                  {timeline.data.slice(0, 30).map((event) => (
                    <li key={event.id} className="flex gap-3">
                      <span
                        className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                          event.type === "error"
                            ? "bg-danger"
                            : event.type === "tool_result"
                              ? "bg-accent"
                              : event.type === "state_change"
                                ? "bg-info"
                                : "bg-line-strong"
                        }`}
                      />
                      <div className="min-w-0">
                        <p className="log-row break-words text-ink-2">{event.message}</p>
                        <p className="text-[11px] text-faint">
                          {event.type} · {formatDate(event.created_at)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                <EmptyState
                  title="Nothing executed yet"
                  description="Tool calls and state transitions appear here in real time."
                />
              )}
            </Card>
          </div>
        ) : null}

        {/* ---------------------------------------------------------- memory */}
        {tab === "memory" ? (
          <div className="grid gap-4 lg:grid-cols-[1fr_0.8fr]">
            <Card>
              <SectionTitle
                title="Stored memory"
                subtitle="Facts this employee retained between sessions."
                action={
                  memory.data && memory.data.length > 0 ? (
                    <Button
                      size="sm"
                      variant="quiet"
                      onClick={async () => {
                        if (!window.confirm("Delete all stored memory for this employee?")) return;
                        await del(`/api/employees/${id}/memory`);
                        memory.refetch();
                      }}
                    >
                      Clear all
                    </Button>
                  ) : undefined
                }
              />
              {memory.loading && !memory.data ? (
                <Loading />
              ) : memory.data && memory.data.length > 0 ? (
                <ul className="divide-y divide-line">
                  {memory.data.map((entry) => (
                    <li key={entry.id} className="flex items-start gap-3 py-3">
                      <Brain size={15} className="mt-1 shrink-0 text-accent" />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium">
                          {entry.key}
                          {entry.pinned ? <Badge tone="accent" className="ml-2">pinned</Badge> : null}
                        </p>
                        <p className="text-sm text-muted">{entry.content}</p>
                        <p className="mt-0.5 text-xs text-faint">
                          {entry.kind} · updated {relativeTime(entry.updated_at)}
                        </p>
                      </div>
                      <Button size="sm" variant="quiet" onClick={() => removeMemory(entry.id)}>
                        <Trash2 size={13} />
                      </Button>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  title="No memory stored"
                  description="Employees call save_memory during tasks, and completed work is summarised automatically when memory is enabled."
                />
              )}
            </Card>

            <Card>
              <SectionTitle title="Add memory" subtitle="Approved, reusable knowledge you want to pin." />
              {!form.memory_enabled ? (
                <Notice message="Memory is disabled for this employee. Enable it in Settings." tone="warning" />
              ) : null}
              <form onSubmit={addMemory} className="space-y-3">
                <Field label="Key">
                  <Input
                    value={memoryKey}
                    onChange={(event) => setMemoryKey(event.target.value)}
                    placeholder="preferred report format"
                    required
                  />
                </Field>
                <Field label="Content">
                  <Textarea
                    rows={4}
                    value={memoryContent}
                    onChange={(event) => setMemoryContent(event.target.value)}
                    placeholder="Markdown with a summary table and cited URLs"
                    required
                  />
                </Field>
                <Button type="submit" variant="primary" disabled={!form.memory_enabled || !memoryKey.trim()}>
                  Save memory
                </Button>
              </form>
              <p className="mt-3 text-xs text-muted">
                Credentials and secret-looking values are refused — memory is shown to the model, so
                it must stay non-sensitive.
              </p>
            </Card>
          </div>
        ) : null}

        {/* ------------------------------------------------------ permissions */}
        {tab === "tools" ? (
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <SectionTitle
                title="Permission policy"
                subtitle="Least privilege by default. Changes apply to the next execution."
              />
              <div className="space-y-4">
                {Object.entries(PERMISSION_HELP).map(([key, meta]) => (
                  <Field key={key} label={meta.label}>
                    <Select
                      value={String((form.permissions ?? {})[key] ?? "none")}
                      onChange={(event) => setPermission(key, event.target.value)}
                    >
                      {meta.options.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </Select>
                  </Field>
                ))}
                <div className="space-y-2.5 border-t border-line pt-4">
                  <Toggle
                    checked={Boolean((form.permissions ?? {}).delegation)}
                    onChange={(value) =>
                      setForm({
                        ...form,
                        permissions: { ...(form.permissions ?? {}), delegation: value },
                      })
                    }
                    label="May delegate tasks to other employees"
                  />
                  <Toggle
                    checked={Boolean((form.permissions ?? {}).capability_create)}
                    onChange={(value) =>
                      setForm({
                        ...form,
                        permissions: { ...(form.permissions ?? {}), capability_create: value },
                      })
                    }
                    label="May build new capabilities (validated in sandbox)"
                  />
                  <Toggle
                    checked={Boolean((form.permissions ?? {}).publish)}
                    onChange={(value) =>
                      setForm({
                        ...form,
                        permissions: { ...(form.permissions ?? {}), publish: value },
                      })
                    }
                    label="May publish externally (always asks for approval)"
                  />
                </div>
                <Button
                  variant="primary"
                  onClick={saveSettings}
                  disabled={saving}
                >
                  {saving ? "Saving…" : "Save permissions"}
                </Button>
              </div>
            </Card>

            <Card>
              <SectionTitle title="Tool access" subtitle="Everything this employee can call." />
              <div className="space-y-2 text-sm">
                <KeyValue label="Allowlist" value={person.tools_allowlist.length ? person.tools_allowlist.join(", ") : "All permitted tools"} />
                <KeyValue label="Denylist" value={person.tools_denylist.length ? person.tools_denylist.join(", ") : "—"} />
              </div>
              <div className="mt-4 rounded-lg border border-line bg-surface-2 p-3 text-xs text-muted">
                Tools are additionally filtered by the permission policy above: for example a
                employee with <code className="font-mono">network = none</code> never sees
                web_search or web_fetch.
              </div>
              <div className="mt-3">
                <Link href="/tools">
                  <Button size="sm" variant="secondary">
                    <Wrench size={14} /> Inspect tool library
                  </Button>
                </Link>
              </div>
            </Card>
          </div>
        ) : null}

        {/* ---------------------------------------------------- capabilities */}
        {tab === "capabilities" ? (
          <Card>
            <SectionTitle
              title="Capabilities created by this employee"
              subtitle="Generated, tested in the sandbox and registered for reuse."
              action={
                <Link href="/library?new=1">
                  <Button size="sm" variant="secondary">
                    New capability
                  </Button>
                </Link>
              }
            />
            {capabilities.data && capabilities.data.length > 0 ? (
              <ul className="divide-y divide-line">
                {capabilities.data.map((capability) => (
                  <li key={capability.id} className="flex items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium">
                        {capability.name} <span className="text-muted">v{capability.version}</span>
                      </p>
                      <p className="truncate text-xs text-muted">{capability.description}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <Badge tone={(capability as { tests_passed?: boolean }).tests_passed ? "success" : "danger"}>
                        {(capability as { tests_passed?: boolean }).tests_passed ? "tests passed" : "tests failed"}
                      </Badge>
                      <Badge tone={capability.status === "active" ? "accent" : "neutral"}>
                        {capability.status}
                      </Badge>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No capabilities built yet"
                description="When this employee hits a missing capability, it can build one — you approve before it registers."
              />
            )}
          </Card>
        ) : null}

        {/* -------------------------------------------------------- settings */}
        {tab === "settings" ? (
          <form onSubmit={saveSettings} className="grid gap-4 lg:grid-cols-2">
            <Card>
              <SectionTitle title="Identity" />
              <div className="space-y-3">
                <Field label="Name" required>
                  <Input
                    value={form.name ?? ""}
                    onChange={(event) => setForm({ ...form, name: event.target.value })}
                  />
                </Field>
                <Field label="Role">
                  <Input
                    value={form.role ?? ""}
                    onChange={(event) => setForm({ ...form, role: event.target.value })}
                  />
                </Field>
                <Field label="Description">
                  <Textarea
                    rows={2}
                    value={form.description ?? ""}
                    onChange={(event) => setForm({ ...form, description: event.target.value })}
                  />
                </Field>
                <Field
                  label="System instruction"
                  hint="Appended to the Bozii operating rules. Describe style, standards and boundaries."
                >
                  <Textarea
                    rows={7}
                    value={form.system_prompt ?? ""}
                    onChange={(event) => setForm({ ...form, system_prompt: event.target.value })}
                  />
                </Field>
              </div>
            </Card>

            <Card>
              <SectionTitle title="Model & limits" />
              <div className="space-y-3">
                <Field label="Model" hint="Defaults to the platform provider when empty.">
                  <Select
                    value={form.model_id ?? ""}
                    onChange={(event) => setForm({ ...form, model_id: event.target.value || null })}
                  >
                    <option value="">Platform default</option>
                    {(models.data ?? []).map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.display_name || model.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Temperature" hint={`Current: ${form.temperature ?? 0.3}`}>
                  <Input
                    type="number"
                    step="0.1"
                    min="0"
                    max="2"
                    value={form.temperature ?? 0.3}
                    onChange={(event) => setForm({ ...form, temperature: Number(event.target.value) })}
                  />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Max iterations">
                    <Input
                      type="number"
                      min="1"
                      max="100"
                      value={form.max_iterations ?? 12}
                      onChange={(event) => setForm({ ...form, max_iterations: Number(event.target.value) })}
                    />
                  </Field>
                  <Field label="Timeout (seconds)">
                    <Input
                      type="number"
                      min="30"
                      step="30"
                      value={form.timeout_seconds ?? 600}
                      onChange={(event) => setForm({ ...form, timeout_seconds: Number(event.target.value) })}
                    />
                  </Field>
                </div>
                <Toggle
                  checked={Boolean(form.memory_enabled)}
                  onChange={(value) => setForm({ ...form, memory_enabled: value })}
                  label="Remember context between tasks"
                />
                <div className="flex items-center gap-2 border-t border-line pt-4">
                  <Button type="submit" variant="primary" disabled={saving}>
                    {saving ? "Saving…" : "Save settings"}
                  </Button>
                  <span className="text-xs text-muted">
                    <CheckCircle2 size={12} className="mr-1 inline text-success" />
                    Changes are audited
                  </span>
                </div>
              </div>
            </Card>
          </form>
        ) : null}
      </div>
    </div>
  );
}