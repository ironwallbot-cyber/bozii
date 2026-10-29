"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Play, Plus, Search } from "lucide-react";
import { PageHeader } from "@/components/shell";
import {
  Button,
  EmptyState,
  ErrorNote,
  Field,
  Input,
  Loading,
  Modal,
  Select,
  StateBadge,
  Textarea,
  Toggle,
} from "@/components/ui";
import { errorMessage, post } from "@/lib/api";
import { useApi, useSSE } from "@/lib/hooks";
import type { Employee, Task, TaskState } from "@/lib/types";
import { STATE_LABELS, relativeTime } from "@/lib/format";

const FILTERS: { key: string; label: string }[] = [
  { key: "", label: "All" },
  { key: "running,planning,queued,recovering", label: "In flight" },
  { key: "waiting_approval", label: "Needs approval" },
  { key: "completed", label: "Completed" },
  { key: "failed,cancelled", label: "Failed" },
  { key: "paused", label: "Paused" },
];

function NewTaskModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (task: Task) => void;
}) {
  const employees = useApi<Employee[]>(open ? "/api/employees" : null);
  const [employeeId, setEmployeeId] = useState("");
  const [objective, setObjective] = useState("");
  const [title, setTitle] = useState("");
  const [plan, setPlan] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!employeeId && employees.data?.length) setEmployeeId(employees.data[0].id);
  }, [employees.data, employeeId]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const task = await post<Task>("/api/tasks", {
        employee_id: employeeId,
        objective: objective.trim(),
        title: title.trim() || undefined,
        plan_enabled: plan,
      });
      setObjective("");
      setTitle("");
      onCreated(task);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Assign a task" width="max-w-2xl">
      {employees.data && employees.data.length === 0 ? (
        <EmptyState
          title="No employees yet"
          description="Hire an employee first — every task needs someone to run it."
          action={
            <a href="/employees?new=1">
              <Button variant="primary">Hire an employee</Button>
            </a>
          }
        />
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Field label="Employee" required>
            <Select value={employeeId} onChange={(event) => setEmployeeId(event.target.value)}>
              {(employees.data ?? []).map((employee) => (
                <option key={employee.id} value={employee.id}>
                  {employee.name} — {employee.role}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Title" hint="Optional — defaults to the first line of the objective.">
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Competitor research brief"
            />
          </Field>
          <Field label="Objective" required>
            <Textarea
              rows={6}
              required
              value={objective}
              onChange={(event) => setObjective(event.target.value)}
              placeholder="Describe the outcome you want. Include constraints, formats and what 'done' means."
            />
          </Field>
          <Toggle checked={plan} onChange={setPlan} label="Create an execution plan first" />
          {error ? <ErrorNote message={error} /> : null}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="quiet" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={busy || !objective.trim()}>
              <Play size={15} /> Start task
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function TasksContent() {
  const router = useRouter();
  const params = useSearchParams();
  const [filter, setFilter] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const tasks = useApi<Task[]>(`/api/tasks${filter ? `?state=${filter}` : ""}`, 3000);

  useEffect(() => {
    if (params.get("new") === "1") setOpen(true);
  }, [params]);

  useSSE(["activity"], () => tasks.refetch());

  const filtered = (tasks.data ?? []).filter((task) =>
    query.trim()
      ? task.title.toLowerCase().includes(query.trim().toLowerCase()) ||
        task.objective.toLowerCase().includes(query.trim().toLowerCase())
      : true,
  );

  return (
    <div className="reveal">
      <PageHeader
        title="Tasks"
        description="Every objective delegated to your workforce, with its full lifecycle."
        action={
          <Button variant="primary" onClick={() => setOpen(true)}>
            <Plus size={15} /> New task
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {FILTERS.map((item) => (
          <button
            key={item.label}
            onClick={() => setFilter(item.key)}
            className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
              filter === item.key
                ? "border-graphite bg-graphite text-white"
                : "border-line bg-surface text-ink-2 hover:bg-surface-2"
            }`}
          >
            {item.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5">
          <Search size={14} className="text-muted" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search tasks"
            className="w-40 bg-transparent text-sm outline-none sm:w-56"
          />
        </div>
      </div>

      {tasks.loading && !tasks.data ? (
        <Loading label="Loading tasks…" />
      ) : tasks.error ? (
        <ErrorNote message={tasks.error} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={filter || query ? "No tasks match" : "No tasks yet"}
          description={
            filter || query
              ? "Adjust the filters to see more."
              : "Assign an objective to an employee and the engine takes it from there."
          }
          action={
            !filter && !query ? (
              <Button variant="primary" onClick={() => setOpen(true)}>
                <Plus size={15} /> Create the first task
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="panel overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wider text-muted">
                <th className="px-4 py-2.5 font-medium">Task</th>
                <th className="hidden px-4 py-2.5 font-medium sm:table-cell">Employee</th>
                <th className="px-4 py-2.5 font-medium">State</th>
                <th className="hidden px-4 py-2.5 font-medium md:table-cell">Progress</th>
                <th className="hidden px-4 py-2.5 font-medium md:table-cell">Created</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {filtered.map((task) => (
                <tr
                  key={task.id}
                  className="cursor-pointer transition-colors hover:bg-surface-2"
                  onClick={() => router.push(`/tasks/${task.id}`)}
                >
                  <td className="max-w-md px-4 py-3">
                    <p className="truncate font-medium">{task.title}</p>
                    <p className="truncate text-xs text-muted">{task.objective.slice(0, 110)}</p>
                  </td>
                  <td className="hidden px-4 py-3 text-ink-2 sm:table-cell">
                    {task.employee_name?.slice(0, 8) ?? task.employee_id.slice(0, 8)}
                  </td>
                  <td className="px-4 py-3">
                    <StateBadge state={task.state} />
                  </td>
                  <td className="hidden px-4 py-3 text-xs text-muted md:table-cell">
                    {task.iterations_used}/{task.max_iterations} iterations · {task.tool_calls} tool calls
                  </td>
                  <td className="hidden px-4 py-3 text-xs text-muted md:table-cell">
                    {relativeTime(task.created_at)}
                  </td>
                  <td className="px-4 py-3 text-right text-xs text-accent">Open</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <NewTaskModal
        open={open}
        onClose={() => setOpen(false)}
        onCreated={(task) => {
          setOpen(false);
          router.push(`/tasks/${task.id}`);
        }}
      />
    </div>
  );
}

export default function TasksPage() {
  return (
    <Suspense fallback={<Loading />}>
      <TasksContent />
    </Suspense>
  );
}
