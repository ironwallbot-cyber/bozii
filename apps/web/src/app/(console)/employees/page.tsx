"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Plus, Search } from "lucide-react";
import { PageHeader } from "@/components/shell";
import {
  Avatar,
  Badge,
  Button,
  EmptyState,
  ErrorNote,
  Field,
  Input,
  Loading,
  Modal,
  Select,
  Textarea,
} from "@/components/ui";
import { errorMessage, get, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Employee, EmployeeTemplate, ModelInfo } from "@/lib/types";
import { colorFor, relativeTime } from "@/lib/format";

function NewEmployeeModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (employee: Employee) => void;
}) {
  const templates = useApi<EmployeeTemplate[]>(open ? "/api/employees/templates" : null);
  const models = useApi<ModelInfo[]>(open ? "/api/models" : null);
  const [template, setTemplate] = useState("general");
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [description, setDescription] = useState("");
  const [modelId, setModelId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await post<Employee>("/api/employees", {
        name: name.trim(),
        template: template || null,
        role: role.trim() || undefined,
        description: description.trim() || undefined,
        model_id: modelId || null,
      });
      onCreated(created);
      setName("");
      setRole("");
      setDescription("");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Hire an employee" width="max-w-2xl">
      <form onSubmit={submit} className="space-y-4">
        <div>
          <p className="text-sm font-medium text-ink-2">Template</p>
          <p className="text-xs text-muted">
            Templates only set the starting role, prompt and permissions — everything stays editable.
          </p>
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            {(templates.data ?? []).map((item) => {
              const active = template === item.key;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => setTemplate(item.key)}
                  className={`rounded-xl border px-3 py-2.5 text-left transition-colors ${
                    active ? "border-accent bg-accent-soft" : "border-line hover:bg-surface-2"
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <span
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ background: item.avatar_color }}
                    />
                    <span className="text-sm font-medium">{item.name}</span>
                  </span>
                  <span className="mt-1 block text-xs leading-snug text-muted">{item.description}</span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" required>
            <Input
              required
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Ada"
            />
          </Field>
          <Field label="Role">
            <Input
              value={role}
              onChange={(event) => setRole(event.target.value)}
              placeholder="Defaults to the template role"
            />
          </Field>
        </div>

        <Field label="Description">
          <Textarea
            rows={2}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What this employee is responsible for"
          />
        </Field>

        <Field label="Model" hint="Leave empty to use the platform default provider.">
          <Select value={modelId} onChange={(event) => setModelId(event.target.value)}>
            <option value="">Platform default</option>
            {(models.data ?? []).map((model) => (
              <option key={model.id} value={model.id}>
                {model.display_name || model.name}
              </option>
            ))}
          </Select>
        </Field>

        {error ? <ErrorNote message={error} /> : null}

        <div className="flex justify-end gap-2">
          <Button type="button" variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
            {busy ? "Creating…" : "Create employee"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default function EmployeesPage() {
  const router = useRouter();
  const params = useSearchParams();
  const employees = useApi<Employee[]>("/api/employees", 0);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (params.get("new") === "1") setOpen(true);
  }, [params]);

  const filtered = (employees.data ?? []).filter((employee) => {
    const needle = query.trim().toLowerCase();
    if (!needle) return true;
    return (
      employee.name.toLowerCase().includes(needle) ||
      employee.role.toLowerCase().includes(needle) ||
      employee.description.toLowerCase().includes(needle)
    );
  });

  return (
    <div className="reveal">
      <PageHeader
        title="Employees"
        description="Hire, configure and inspect the members of your workforce."
        action={
          <Button variant="primary" onClick={() => setOpen(true)}>
            <Plus size={15} /> New employee
          </Button>
        }
      />

      <div className="mb-4 flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2">
        <Search size={15} className="text-muted" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search by name, role or description"
          className="w-full bg-transparent text-sm outline-none"
        />
      </div>

      {employees.loading && !employees.data ? (
        <Loading label="Loading employees…" />
      ) : employees.error ? (
        <ErrorNote message={employees.error} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={query ? "No matching employees" : "No employees yet"}
          description={
            query
              ? "Try a different search term."
              : "Start from a template — General Assistant, Software Engineer, Web Researcher and six more."
          }
          action={
            !query ? (
              <Button variant="primary" onClick={() => setOpen(true)}>
                <Plus size={15} /> Hire your first employee
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((employee) => (
            <button
              key={employee.id}
              onClick={() => router.push(`/employees/${employee.id}`)}
              className="panel p-4 text-left transition-colors hover:border-line-strong"
            >
              <div className="flex items-start gap-3">
                <Avatar
                  name={employee.name}
                  color={employee.avatar_color || colorFor(employee.id)}
                  seed={employee.avatar_seed}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate font-medium">{employee.name}</p>
                    <Badge tone={employee.status === "active" ? "success" : "neutral"}>
                      {employee.status}
                    </Badge>
                  </div>
                  <p className="truncate text-sm text-muted">{employee.role}</p>
                  <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-muted">
                    {employee.description || "No description yet."}
                  </p>
                </div>
              </div>
              <div className="mt-3 flex items-center gap-3 border-t border-line pt-3 text-xs text-muted">
                <span>{employee.active_tasks} active</span>
                <span className="text-success">{employee.completed_tasks} done</span>
                <span className={employee.failed_tasks ? "text-danger" : ""}>
                  {employee.failed_tasks} failed
                </span>
                <span className="ml-auto">{relativeTime(employee.updated_at)}</span>
              </div>
            </button>
          ))}
        </div>
      )}

      <NewEmployeeModal
        open={open}
        onClose={() => setOpen(false)}
        onCreated={(employee) => {
          setOpen(false);
          router.push(`/employees/${employee.id}`);
        }}
      />
    </div>
  );
}