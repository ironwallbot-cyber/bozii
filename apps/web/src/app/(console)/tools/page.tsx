"use client";

import { useState } from "react";
import { ChevronDown, Shield, Wrench } from "lucide-react";
import { PageHeader } from "@/components/shell";
import { Badge, Button, Card, EmptyState, ErrorNote, Loading, Toggle } from "@/components/ui";
import { errorMessage, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Tool } from "@/lib/types";

const RISK_TONE: Record<string, string> = {
  safe: "success",
  mutating: "warning",
  consequential: "danger",
};

function PermissionChips({ permissions }: { permissions: Record<string, unknown> }) {
  const entries = Object.entries(permissions ?? {});
  if (entries.length === 0) return <Badge tone="success">no special permission</Badge>;
  return (
    <>
      {entries.map(([key, value]) => (
        <Badge key={key} tone={value === false || value === "none" ? "neutral" : "warning"}>
          {key}: {String(value)}
        </Badge>
      ))}
    </>
  );
}

function ToolRow({
  tool,
  onToggle,
}: {
  tool: Tool;
  onToggle: (name: string, enabled: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const properties = Object.entries(tool.parameters?.properties ?? {});

  return (
    <div className="border-b border-line last:border-b-0">
      <div className="flex items-start gap-3 px-4 py-3">
        <Wrench size={15} className="mt-1 shrink-0 text-muted" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setOpen((value) => !value)}
              className="text-sm font-medium hover:text-accent"
            >
              {tool.name}
            </button>
            <Badge>{tool.category}</Badge>
            <Badge tone={RISK_TONE[tool.risk] ?? "neutral"}>{tool.risk}</Badge>
            {tool.kind === "capability" ? <Badge tone="accent">capability</Badge> : null}
            {!tool.enabled ? <Badge tone="danger">disabled</Badge> : null}
          </div>
          <p className="mt-1 text-sm text-muted">{tool.description}</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <PermissionChips permissions={tool.required_permissions} />
          </div>

          {open ? (
            <div className="mt-3 rounded-xl border border-line bg-surface-2 p-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted">
                Input schema
              </p>
              {properties.length > 0 ? (
                <ul className="mt-2 space-y-1.5">
                  {properties.map(([name, schema]) => (
                    <li key={name} className="text-xs">
                      <code className="font-mono text-ink">{name}</code>
                      {schema?.type ? <span className="text-muted"> : {schema.type}</span> : null}
                      {schema?.enum ? (
                        <span className="text-muted"> ({schema.enum.join(" | ")})</span>
                      ) : null}
                      {schema?.description ? (
                        <span className="block text-muted">{schema.description}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1 text-xs text-muted">No parameters — runs as-is.</p>
              )}
              <p className="mt-2 text-xs text-muted">
                version {tool.version}
                {tool.capability_id ? " · generated capability executed in the sandbox" : " · builtin"}
              </p>
            </div>
          ) : null}
        </div>

        <div className="shrink-0">
          <Toggle
            checked={tool.enabled}
            onChange={(value) => onToggle(tool.name, value)}
            disabled={tool.kind === "capability"}
          />
        </div>
      </div>
    </div>
  );
}

export default function ToolsPage() {
  const tools = useApi<Tool[]>("/api/tools", 0);
  const [error, setError] = useState<string | null>(null);

  const toggle = async (name: string, enabled: boolean) => {
    setError(null);
    try {
      await post(`/api/tools/${name}/toggle`, { enabled });
      tools.refetch();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  if (tools.loading && !tools.data) return <Loading label="Loading tools…" />;
  if (!tools.data) return <ErrorNote message={tools.error ?? "Could not load tools"} />;

  const grouped = tools.data.reduce<Record<string, Tool[]>>((acc, tool) => {
    (acc[tool.category] ??= []).push(tool);
    return acc;
  }, {});

  const builtin = tools.data.filter((tool) => tool.kind === "builtin").length;
  const generated = tools.data.length - builtin;

  return (
    <div className="reveal">
      <PageHeader
        title="Tools & Skills"
        description="The execution surface available to your employees."
        action={
          <span className="flex items-center gap-2 text-xs text-muted">
            <Badge tone="success">{builtin} builtin</Badge>
            <Badge tone="accent">{generated} capability</Badge>
          </span>
        }
      />

      {error ? <div className="mb-4"><ErrorNote message={error} /></div> : null}

      <div className="mb-4 rounded-xl border border-line bg-surface p-4 text-sm text-muted">
        <span className="flex items-start gap-2">
          <Shield size={15} className="mt-0.5 shrink-0 text-accent" />
          Tools are filtered per employee: an employee only ever sees tools its permission policy
          satisfies, and disabling a tool here removes it from every task immediately.
        </span>
      </div>

      <div className="space-y-4">
        {Object.entries(grouped)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([category, items]) => (
            <Card key={category} padded={false}>
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <h2 className="text-sm font-semibold capitalize">{category}</h2>
                <span className="text-xs text-muted">{items.length} tools</span>
              </div>
              {items.map((tool) => (
                <ToolRow key={tool.name} tool={tool} onToggle={toggle} />
              ))}
            </Card>
          ))}
        {tools.data.length === 0 ? (
          <EmptyState title="No tools registered" description="The tool registry is empty." />
        ) : null}
      </div>
    </div>
  );
}
