"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { Boxes, Plus, Send, Trash2, UserPlus } from "lucide-react";
import { PageHeader } from "@/components/shell";
import {
  Avatar,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Field,
  Input,
  Loading,
  Modal,
  SectionTitle,
  Select,
  StateBadge,
  Textarea,
} from "@/components/ui";
import { del, errorMessage, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Employee, Team, TeamMessage, Task } from "@/lib/types";
import { relativeTime } from "@/lib/format";

function NewTeamModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (team: Team) => void;
}) {
  const employees = useApi<Employee[]>(open ? "/api/employees" : null);
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [lead, setLead] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (id: string) =>
    setMembers((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const team = await post<Team>("/api/teams", {
        name: name.trim(),
        objective: objective.trim(),
        member_ids: members,
        lead_employee_id: lead || members[0] || null,
      });
      setName("");
      setObjective("");
      setMembers([]);
      onCreated(team);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Create a team" width="max-w-2xl">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Team name" required>
          <Input required value={name} onChange={(event) => setName(event.target.value)} placeholder="Launch crew" />
        </Field>
        <Field label="Shared objective" hint="Context every member can see when working together.">
          <Textarea
            rows={3}
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
            placeholder="Ship the beta announcement site: research, copy, build, review."
          />
        </Field>
        <Field label="Members">
          <div className="mt-1 grid gap-2 sm:grid-cols-2">
            {(employees.data ?? []).map((employee) => {
              const active = members.includes(employee.id);
              return (
                <button
                  key={employee.id}
                  type="button"
                  onClick={() => toggle(employee.id)}
                  className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-left text-sm transition-colors ${
                    active ? "border-accent bg-accent-soft" : "border-line hover:bg-surface-2"
                  }`}
                >
                  <Avatar name={employee.name} color={employee.avatar_color} size={24} />
                  <span className="min-w-0 flex-1 truncate">{employee.name}</span>
                  <span className="text-xs text-muted">{employee.role}</span>
                </button>
              );
            })}
            {(employees.data ?? []).length === 0 ? (
              <p className="text-sm text-muted">Create employees first to build a team.</p>
            ) : null}
          </div>
        </Field>
        {members.length > 0 ? (
          <Field label="Lead">
            <Select value={lead || members[0]} onChange={(event) => setLead(event.target.value)}>
              {members.map((id) => {
                const employee = (employees.data ?? []).find((item) => item.id === id);
                return (
                  <option key={id} value={id}>
                    {employee?.name ?? id}
                  </option>
                );
              })}
            </Select>
          </Field>
        ) : null}
        {error ? <ErrorNote message={error} /> : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
            Create team
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default function TeamsPage() {
  const teams = useApi<Team[]>("/api/teams", 5000);
  const employees = useApi<Employee[]>("/api/employees");
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [assignTo, setAssignTo] = useState("");
  const [objective, setObjective] = useState("");
  const [message, setMessage] = useState("");

  const active = teams.data?.find((team) => team.id === selected) ?? null;
  const messages = useApi<TeamMessage[]>(
    selected ? `/api/teams/${selected}/messages` : null,
    4000,
  );
  const teamTasks = useApi<Task[]>(selected ? `/api/tasks?team_id=${selected}` : null, 4000);

  const assign = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    setError(null);
    try {
      await post(`/api/teams/${selected}/tasks`, {
        objective: objective.trim(),
        employee_id: assignTo || undefined,
      });
      setObjective("");
      teamTasks.refetch();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  const sendMessage = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    setError(null);
    try {
      await post(`/api/teams/${selected}/messages`, { content: message.trim() });
      setMessage("");
      messages.refetch();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  return (
    <div className="reveal">
      <PageHeader
        title="Teams"
        description="Group employees around a shared objective and coordinate their work."
        action={
          <Button variant="primary" onClick={() => setOpen(true)}>
            <Plus size={15} /> New team
          </Button>
        }
      />

      {teams.loading && !teams.data ? (
        <Loading />
      ) : teams.data && teams.data.length === 0 ? (
        <EmptyState
          title="No teams yet"
          description="Teams let one employee coordinate others — with bounded depth and shared permissions."
          action={
            <Button variant="primary" onClick={() => setOpen(true)}>
              <Plus size={15} /> Create a team
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
          <Card padded={false}>
            <ul className="divide-y divide-line">
              {(teams.data ?? []).map((team) => (
                <li key={team.id}>
                  <button
                    onClick={() => setSelected(team.id)}
                    className={`flex w-full items-center gap-3 px-4 py-3 text-left transition-colors ${
                      selected === team.id ? "bg-surface-2" : "hover:bg-surface-2"
                    }`}
                  >
                    <Boxes size={16} className="shrink-0 text-accent" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{team.name}</p>
                      <p className="text-xs text-muted">
                        {team.members.length} member{team.members.length === 1 ? "" : "s"} ·{" "}
                        {team.task_count} tasks
                      </p>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </Card>

          {active ? (
            <div className="space-y-4">
              <Card>
                <SectionTitle
                  title={active.name}
                  subtitle={active.objective || active.description || "No shared objective yet."}
                  action={
                    <Button
                      size="sm"
                      variant="quiet"
                      onClick={async () => {
                        if (!window.confirm(`Delete team ${active.name}?`)) return;
                        await del(`/api/teams/${active.id}`);
                        setSelected(null);
                        teams.refetch();
                      }}
                    >
                      <Trash2 size={14} />
                    </Button>
                  }
                />
                <div className="grid gap-2 sm:grid-cols-2">
                  {active.members.map((member) => (
                    <div
                      key={member.id}
                      className="flex items-center gap-2.5 rounded-xl border border-line px-3 py-2"
                    >
                      <Avatar name={member.employee_name} size={28} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{member.employee_name}</p>
                        <p className="text-xs text-muted">{member.role}</p>
                      </div>
                      <Link href={`/employees/${member.employee_id}`} className="text-xs text-accent">
                        open
                      </Link>
                    </div>
                  ))}
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <form onSubmit={assign} className="space-y-2">
                    <Field label="Assign objective to the team">
                      <Textarea
                        rows={3}
                        value={objective}
                        onChange={(event) => setObjective(event.target.value)}
                        placeholder="Draft the launch announcement and fact-check every claim."
                        required
                      />
                    </Field>
                    <div className="flex gap-2">
                      <Select value={assignTo} onChange={(event) => setAssignTo(event.target.value)}>
                        <option value="">Lead (default)</option>
                        {active.members.map((member) => (
                          <option key={member.employee_id} value={member.employee_id}>
                            {member.employee_name}
                          </option>
                        ))}
                      </Select>
                      <Button type="submit" variant="primary" disabled={!objective.trim()}>
                        Assign
                      </Button>
                    </div>
                  </form>

                  <form onSubmit={sendMessage} className="space-y-2">
                    <Field label="Message the team">
                      <Textarea
                        rows={3}
                        value={message}
                        onChange={(event) => setMessage(event.target.value)}
                        placeholder="Reminder: cite sources for every statistic."
                      />
                    </Field>
                    <Button type="submit" disabled={!message.trim()}>
                      <Send size={14} /> Send
                    </Button>
                  </form>
                </div>
                {error ? <div className="mt-3"><ErrorNote message={error} /></div> : null}
              </Card>

              <div className="grid gap-4 md:grid-cols-2">
                <Card>
                  <SectionTitle title="Team tasks" />
                  {teamTasks.data && teamTasks.data.length > 0 ? (
                    <ul className="divide-y divide-line">
                      {teamTasks.data.map((task) => (
                        <li key={task.id}>
                          <Link
                            href={`/tasks/${task.id}`}
                            className="flex items-center justify-between gap-3 py-2.5 hover:bg-surface-2"
                          >
                            <span className="min-w-0 truncate text-sm">{task.title}</span>
                            <StateBadge state={task.state} />
                          </Link>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <EmptyState title="No team tasks" description="Assign an objective to get started." />
                  )}
                </Card>

                <Card>
                  <SectionTitle title="Messages" />
                  {messages.data && messages.data.length > 0 ? (
                    <ul className="max-h-72 space-y-3 overflow-y-auto">
                      {messages.data.map((item) => (
                        <li key={item.id} className="rounded-lg bg-surface-2 px-3 py-2 text-sm">
                          <p className="whitespace-pre-wrap text-ink-2">{item.content}</p>
                          <p className="mt-1 text-xs text-muted">{relativeTime(item.created_at)}</p>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-muted">No messages yet.</p>
                  )}
                </Card>
              </div>
            </div>
          ) : (
            <EmptyState
              title="Select a team"
              description="Pick a team on the left to assign work and coordinate members."
            />
          )}
        </div>
      )}

      <NewTeamModal
        open={open}
        onClose={() => setOpen(false)}
        onCreated={(team) => {
          setOpen(false);
          setSelected(team.id);
          teams.refetch();
        }}
      />
    </div>
  );
}
