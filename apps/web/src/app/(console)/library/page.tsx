"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  FileCode,
  Filter,
  FolderOpen,
  GitBranch,
  Image,
  Import,
  RotateCcw,
  Search,
  Shield,
  Upload,
  XCircle,
} from "lucide-react";
import { PageHeader } from "@/components/shell";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Field,
  Input,
  Loading,
  Modal,
  StateBadge,
  Tabs,
  Textarea,
} from "@/components/ui";
import { del, errorMessage, get, patch, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Capability, Tool } from "@/lib/types";
import { formatDate, relativeTime } from "@/lib/format";

const FILTER_ALL = "all";
const VISIBILITY_PRIVACY_NOTE = "Private capabilities belong to your workspace. Public ones are visible to others who can install them after validation.";

function CapabilityCard({
  capability,
  onInstall,
}: {
  capability: Capability;
  onInstall?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const risk =
    capability.permissions.some((p) =>
      ["fs_write", "exec", "delegation", "publish"].includes(p),
    )
      ? "mutating"
      : "safe";

  return (
    <Card padded={false} className="overflow-hidden">
      <div className="flex items-start gap-3 px-4 py-3">
        <div className="mt-0.5 shrink-0 rounded-lg bg-surface-2 p-2">
          {capability.kind === "skill" ? (
            <FolderOpen size={16} className="text-muted" />
          ) : (
            <FileCode size={16} className="text-muted" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setOpen((v) => !v)}
              className="text-sm font-medium hover:text-accent"
            >
              {capability.name}
            </button>
            <Badge>v{capability.version}</Badge>
            <Badge tone={capability.status === "active" ? "success" : "neutral"}>
              {capability.status}
            </Badge>
            <Badge tone={capability.visibility === "public" ? "accent" : "neutral"}>
              {capability.visibility}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-muted">{capability.description}</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {capability.tags.length > 0 ? (
              capability.tags.map((tag) => (
                <span key={tag} className="rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[11px]">
                  {tag}
                </span>
              ))
            ) : null}
            {capability.permissions.length > 0 ? (
              <span className="text-[11px] text-muted">
                requires {capability.permissions.join(", ")}
              </span>
            ) : null}
          </div>

          {open ? (
            <div className="mt-3 rounded-xl border border-line bg-surface-2 p-3 text-sm">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted">
                Manifest
              </p>
              <pre className="mt-1 overflow-x-auto text-muted">
                {JSON.stringify(
                  {
                    kind: capability.kind,
                    category: capability.category,
                    permissions: capability.permissions,
                    dependencies: capability.dependencies,
                    input_schema: capability.input_schema,
                  },
                  null,
                  2,
                )}
              </pre>
              <p className="mt-2 text-xs text-muted">
                Created {relativeTime(capability.created_at)}
                {capability.activated_at ? ` · activated ${formatDate(capability.activated_at)}` : ""}
                {"tests_passed" in capability && capability.tests_passed !== undefined ? (
                  <span className="ml-2">
                    {" "}
                    · {capability.tests_passed ? "tests passed" : "tests failed"}
                  </span>
                ) : null}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {capability.status === "active" && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      setOpen(false);
                      patch(`/api/capabilities/${capability.id}/status`, {
                        status: "disabled",
                      }).then(() => onInstall && onInstall());
                    }}
                  >
                    <RotateCcw size={13} /> Deactivate
                  </Button>
                )}
                {capability.status !== "active" && (
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => {
                      setOpen(false);
                      patch(`/api/capabilities/${capability.id}/status`, {
                        status: "active",
                      }).then(() => onInstall && onInstall());
                    }}
                  >
                    <RotateCcw size={13} /> Activate
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="quiet"
                  onClick={() => setOpen(false)}
                >
                  Close
                </Button>
              </div>
              {capability.visibility === "private" ? (
                <div className="mt-2 border-t border-line pt-3 space-y-2">
                  <Textarea
                    rows={4}
                    readOnly
                    value={capability.provenance?.toString() ?? ""}
                    className="bg-surface text-xs"
                    placeholder="Provenance is stored as a string representation of the origin record."
                  />
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="shrink-0">
          {capability.status === "active" ? (
            <Button size="sm" variant="secondary" onClick={() => onInstall && onInstall()}>
              <Import size={13} /> Install
            </Button>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

function LibraryContent() {
  const router = useRouter();
  const params = useSearchParams();
  const [visibility, setVisibility] = useState<string>(
    params.get("visibility") ?? FILTER_ALL,
  );
  const [query, setQuery] = useState("");
  const capabilities = useApi<Capability[]>(
    `/api/library${visibility !== FILTER_ALL ? `?visibility=${visibility}` : ""}`,
    3000,
  );
  const tools = useApi<Tool[]>("/api/tools", 0);
  const installed = useApi<Capability[]>("/api/capabilities/installed", 4000);

  const combined = useState("all");
  const [newBundle, setNewBundle] = useState("");

  const q = query.trim().toLowerCase();
  const source =
    visibility === FILTER_ALL
      ? capabilities.data
      : capabilities.data?.filter((c) => c.visibility === visibility) ??
        [];
  const installedIds = new Set(installed.data?.map((c) => c.id) ?? []);
  const available = source?.filter(
    (c) =>
      !q ||
      c.name.toLowerCase().includes(q) ||
      c.description.toLowerCase().includes(q) ||
      c.tags.some((t) => t.toLowerCase().includes(q)),
  );

  return (
    <div className="reveal">
      <PageHeader
        title="Capability Library"
        description="Reusable tools and skills, validated in the sandbox before they ever run as an employee tool."
        action={
          <div className="flex items-center gap-3">
            <Button variant="secondary" onClick={() => router.push("/library?new=1")}>
              <FileCode size={15} /> New capability
            </Button>              <Button variant="quiet" onClick={() => setImportModal(true)}>
                <Upload size={15} /> Import
              </Button>
          </div>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5">
          <Search size={14} className="text-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search capabilities"
            className="w-40 bg-transparent text-sm outline-none sm:w-56"
          />
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setVisibility(FILTER_ALL)}
            className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
              visibility === FILTER_ALL
                ? "border-graphite bg-graphite text-white"
                : "border-line bg-surface text-ink-2 hover:bg-surface-2"
            }`}
          >
            All
          </button>
          <button
            onClick={() => setVisibility("public")}
            className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
              visibility === "public"
                ? "border-graphite bg-graphite text-white"
                : "border-line bg-surface text-ink-2 hover:bg-surface-2"
            }`}
          >
            Public
          </button>
          <button
            onClick={() => setVisibility("private")}
            className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
              visibility === "private"
                ? "border-graphite bg-graphite text-white"
                : "border-line bg-surface text-ink-2 hover:bg-surface-2"
            }`}
          >
            Private
          </button>
        </div>
      </div>

      {capabilities.error ? (
        <ErrorNote message={capabilities.error} />
      ) : capabilities.loading && !capabilities.data ? (
        <Loading label="Loading library…" />
      ) : (
        <div className="space-y-4">
          <Card>
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <h2 className="text-sm font-semibold capitalize">
                {visibility === FILTER_ALL ? "All capabilities" : visibility}
              </h2>
              <span className="text-xs text-muted">
                {available?.length ?? 0} capability(y)(ies)
              </span>
            </div>
            {(!available || available.length === 0) ? (
              <EmptyState
                title="No capabilities yet"
                description={
                  query
                    ? "Try a different search term."
                    : "Bozii creates capabilities from executed tasks. Enable code generation on an employee that builds something reusable, then approve the result."
                }
              />
            ) : (
              <div className="divide-y divide-line">
                {available?.map((capability) => (
                  <CapabilityCard
                    key={capability.id}
                    capability={capability}
                    onInstall={() => {
                      installed.refetch();
                    }}
                  />
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      <Card className="mt-4">
        <div className="flex items-start gap-3">
          <Shield size={15} className="mt-0.5 shrink-0 text-accent" />
          <div>
            <p className="text-sm font-medium text-ink">Security note</p>
            <p className="mt-0.5 text-sm text-muted">
              Public capabilities are untrusted code. New capabilities are never activated
              automatically unless the platform setting allows it, and they’re always executed
              in an isolated sandbox with resource limits and no network by default.
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}

function OpenImport({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [bundle, setBundle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [result, setResult] = useState<{ id: string } | null>(null);

  const submit = async () => {
    setError(null);
    setOk(true);
    try {
      const parsed = JSON.parse(bundle);
      const res = await post<{ id: string }>("/api/capabilities/import", parsed);
      setResult(res);
      setBundle("");
      onClose();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setOk(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Import capability"
      width="max-w-xl"
    >
      <p className="text-sm text-muted">
        Paste a <code className="font-mono text-ink">bozii-capability</code> bundle exported from
        another workspace.
      </p>
      <Textarea
        rows={10}
        value={bundle}
        onChange={(e) => setBundle(e.target.value)}
        placeholder='{"format":"bozii-capability","format_version":1,"manifest":{...},"files":{...}}'
        required
      />
      {error ? <ErrorNote message={error} /> : null}
      {ok && result ? (
        <div className="rounded-lg border border-success bg-success-soft p-3 text-sm">
          <p className="font-medium text-success">Imported capability id: {result.id}</p>
        </div>
      ) : null}
      <div className="flex justify-end gap-2 mt-3">
        <Button variant="quiet" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={submit}
          disabled={!bundle.trim() || ok}
        >
          Import
        </Button>
      </div>
    </Modal>
  );
}

function NewCapabilityModalInner({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"tool" | "skill">("tool");
  const [category, setCategory] = useState("general");
  const [description, setDescription] = useState("");
  const [permissions, setPermissions] = useState("fs_read");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ id: string } | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const caps = await post<{ id: string }>("/api/capabilities", {
        name: name.trim(),
        kind,
        category,
        description: description.trim(),
        permissions: permissions
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setCreated(caps);
      setName("");
      setDescription("");
      setPermissions("fs_read");
      onClose();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={kind === "skill" ? "New skill" : "New capability"}
      width="max-w-xl"
    >
      <div className="space-y-4">
        <div className="flex gap-4">
          <div className="flex-1">
            <Field label="Name" required>
              <Textarea
                rows={2}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Summarize recent research"
                required
              />
            </Field>
          </div>
          <div className="w-40">
            <Tabs
              tabs={[
                { key: "tool", label: "tool" },
                { key: "skill", label: "skill" },
              ]}
              active={kind}
              onChange={(k) => setKind(k as "tool" | "skill")}
            />
          </div>
        </div>
        <Field label="Description" required>
          <Textarea
            rows={4}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What does this capability do?"
            required
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Category">
            <Input
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="general"
            />
          </Field>
          <Field label="Permissions" hint="Comma-separated permission codes">
            <Input
              value={permissions}
              onChange={(e) => setPermissions(e.target.value)}
              placeholder="fs_read, net_search"
            />
          </Field>
        </div>

        {error ? <ErrorNote message={error} /> : null}
        {created ? (
          <div className="rounded-lg border border-success bg-success-soft p-3 text-sm">
            <p className="font-medium text-success">Capability created</p>
            <p className="text-success">{created.id}</p>
          </div>
        ) : null}

        <div className="flex justify-end gap-2">
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            disabled={!name.trim() || !description.trim() || busy}
          >
            Create
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function NewCapabilityModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <NewCapabilityModalInner open={open} onClose={onClose} />
  );
}

function ModalWrapper({
  open,
  onClose,
  render,
}: {
  open: boolean;
  onClose: () => void;
  render: (open: boolean, onClose: () => void) => React.ReactNode;
}) {
  return render(open, onClose);
}

export default function LibraryPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [newModal, setNewModal] = useState(params.get("new") === "1");
  const [importModal, setImportModal] = useState(false);

  return (
    <Suspense fallback={<Loading label="Loading library…" />}>
      <LibraryContent />
      <NewCapabilityModal
        open={newModal}
        onClose={() => {
          setNewModal(false);
          router.push("/library", undefined, { scroll: false });
        }}
      />
      <ModalWrapper
        open={importModal}
        onClose={() => setImportModal(false)}
        render={(open, onClose) => (
          <OpenImport open={open} onClose={onClose} />
        )}
      />
    </Suspense>
  );
}
