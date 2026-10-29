"use client";

import { useState } from "react";
import { Shield, RefreshCw, Save, CheckCircle2, AlertTriangle, Eye, EyeOff } from "lucide-react";
import { PageHeader } from "@/components/shell";
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  Field,
  Input,
  Loading,
  Notice,
  SectionTitle,
  Select,
  Tabs,
  Textarea,
  Toggle,
} from "@/components/ui";
import { del, errorMessage, get, patch, post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Provider, SandboxReport, AppSettings, AdsPayload } from "@/lib/types";
import { relativeTime } from "@/lib/format";

export default function SettingsPage() {
  const settings = useApi<AppSettings>("/api/settings", 0);
  const providers = useApi<Provider[]>("/api/providers", 0);
  const sandbox = useApi<SandboxReport>("/api/settings/sandbox", 0);
  const ads = useApi<AdsPayload>("/api/settings/ads", 0);

  const [tab, setTab] = useState<"general" | "models" | "sandbox" | "ads">("general");
  const [notice, setNotice] = useState<string | null>(null);

  const tabs: { key: "general" | "models" | "sandbox" | "ads"; label: string }[] = [
    { key: "general", label: "General" },
    { key: "models", label: "Models" },
    { key: "sandbox", label: "Sandbox" },
    { key: "ads", label: "Ads" },
  ];

  if (settings.loading && !settings.data) return <Loading label="Loading settings…" />;
  if (!settings.data) return <ErrorNote message={settings.error ?? "Could not load settings"} />;

  return (
    <div className="reveal">
      <PageHeader
        title="Settings"
        description="Control how your Bozii workspace runs."
      />

      <Tabs tabs={tabs} active={tab} onChange={(k) => setTab(k)} />

      <div className="mt-5 space-y-6">
        {settings.error ? <ErrorNote message={settings.error} /> : null}
        {notice ? <Notice message={notice} /> : null}

        {tab === "general" ? (
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <SectionTitle title="Workspace" />
              <div className="space-y-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted">Name</span>
                  <span className="text-ink">{settings.data.app_name}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Environment</span>
                  <Badge tone={settings.data.environment === "production" ? "success" : "neutral"}>
                    {settings.data.environment}
                  </Badge>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Version</span>
                  <span className="text-ink font-mono text-xs">{settings.data.version}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Signup</span>
                  <span className="text-ink">
                    {settings.data.allow_signup ? "Open" : "Disabled"}
                  </span>
                </div>
              </div>
            </Card>

            <Card>
              <SectionTitle title="Execution limits" />
              <div className="space-y-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted">Workers</span>
                  <span className="text-ink">{settings.data.task_workers}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Max iterations</span>
                  <span className="text-ink">{settings.data.max_iterations}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Task timeout</span>
                  <span className="text-ink">{settings.data.task_timeout_seconds}s</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Sandbox timeout</span>
                  <span className="text-ink">{settings.data.sandbox.timeout_seconds}s</span>
                </div>
              </div>
            </Card>

            <Card>
              <SectionTitle title="Status note" />
              <p className="text-sm text-muted">
                These settings are read from the running API. Some values can be tuned via
                environment variables and deployment configuration rather than this UI.
              </p>
            </Card>
          </div>
        ) : tab === "models" ? (
          <div>
            <Card>
              <SectionTitle
                title="Model providers"
                subtitle="Configure local and remote inference endpoints the employees can use."
                action={
                  <Button variant="secondary" onClick={async () => {
                    try {
                      await post("/api/providers", {
                        name: "New provider",
                        kind: "ollama",
                        is_default: false,
                      });
                      providers.refetch();
                    } catch (caught) {
                      setNotice(errorMessage(caught));
                    }
                  }}>
                    <RefreshCw size={14} /> Add provider
                  </Button>
                }
              />
              {providers.data && providers.data.length > 0 ? (
                <ul className="divide-y divide-line">
                  {providers.data.map((provider) => (
                    <li key={provider.id} className="flex items-center justify-between gap-3 py-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{provider.name}</span>
                          <Badge>{provider.kind}</Badge>
                          {provider.is_default ? <Badge tone="accent">default</Badge> : null}
                          <span className="text-xs text-muted">{provider.base_url}</span>
                        </div>
                        <p className="mt-0.5 text-xs text-muted">
                          {provider.models.length} model(s) ·{" "}
                          {provider.last_health_at
                            ? `last checked ${relativeTime(provider.last_health_at)}`
                            : "never checked"}
                          {provider.last_health_ok === false ? (
                            <span className="text-danger ml-2">
                              {provider.last_health_error?.slice(0, 80)}
                            </span>
                          ) : provider.last_health_ok === true ? (
                            <span className="text-success ml-2">healthy</span>
                          ) : null}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="quiet"
                          onClick={async () => {
                            try {
                              const body = provider.kind === "ollama" ? {} : { base_url: provider.base_url };
                              await patch(`/api/providers/${provider.id}/check`, body);
                              providers.refetch();
                            } catch (caught) {
                              setNotice(errorMessage(caught));
                            }
                          }}
                        >
                          <RefreshCw size={13} /> Check
                        </Button>
                        <Button
                          size="sm"
                          variant="quiet"
                          onClick={async () => {
                            if (!window.confirm("Delete this provider?")) return;
                            await del(`/api/providers/${provider.id}`);
                            providers.refetch();
                          }}
                        >
                          <EyeOff size={13} />
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="py-6 text-sm text-muted">
                  No model providers configured yet. Add one so employees can run tasks with a real model.
                </div>
              )}
            </Card>
          </div>
        ) : tab === "sandbox" ? (
          <Card>
            <SectionTitle
              title="Sandbox status"
              subtitle="Generated code runs here, not in the Bozii process. Status is read from the API."
            />
            {sandbox.data ? (
              <div className="space-y-4 pt-2">
                <div className="rounded-lg border border-line bg-surface-2 p-4 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-muted">Network isolation</span>
                    <Badge tone={sandbox.data.network_isolation ? "success" : "danger"}>
                      {sandbox.data.network_isolation ? "enabled" : "disabled"}
                    </Badge>
                  </div>
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-muted">Privilege drop</span>
                    <Badge tone={sandbox.data.privilege_drop ? "success" : "warning"}>
                      {sandbox.data.privilege_drop ? "dropped" : "not dropped"}
                    </Badge>
                  </div>
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-muted">Running as root</span>
                    <Badge tone={!sandbox.data.running_as_root ? "success" : "danger"}>
                      {sandbox.data.running_as_root ? "yes (reduced isolation)" : "no"}
                    </Badge>
                  </div>
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-muted">Sandbox user</span>
                    <span className="text-ink font-mono text-xs">{sandbox.data.sandbox_user ?? "—"}</span>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-3 text-sm">
                  <div className="rounded-lg border border-line bg-surface-2 p-3">
                    <p className="text-muted text-xs">Timeout</p>
                    <p className="text-ink font-mono">{sandbox.data.timeout_seconds}s</p>
                  </div>
                  <div className="rounded-lg border border-line bg-surface-2 p-3">
                    <p className="text-muted text-xs">Memory</p>
                    <p className="text-ink font-mono">{sandbox.data.memory_mb} MB</p>
                  </div>
                  <div className="rounded-lg border border-line bg-surface-2 p-3">
                    <p className="text-muted text-xs">CPU</p>
                    <p className="text-ink font-mono">{sandbox.data.cpu_seconds}s</p>
                  </div>
                </div>
                {sandbox.data.notes ? (
                  <div className="rounded-lg bg-warning-soft p-3 text-sm text-warning">
                    {sandbox.data.notes}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="py-6 text-sm text-muted">Sandbox status unavailable.</div>
            )}
          </Card>
        ) : tab === "ads" ? (
          <Card>
            <SectionTitle
              title="Advertising"
              subtitle="Non-intrusive placements that never touch model context, secrets or task content."
            />
            {ads.data ? (
              <div className="space-y-4 pt-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-ink">Advertising enabled</span>
                  <Toggle
                    checked={ads.data.enabled}
                    onChange={async (value) => {
                      try {
                        await patch("/api/settings", { enable_ads: value });
                        ads.refetch();
                        setNotice(value ? "Advertising enabled" : "Advertising disabled");
                      } catch (caught) {
                        setNotice(errorMessage(caught));
                      }
                    }}
                  />
                </div>
                <div className="rounded-lg border border-line bg-surface-2 p-4 text-sm">
                  <p className="text-muted">Placement: {ads.data.placement || "—"}</p>
                  <p className="mt-1 text-muted">Provider: {ads.data.provider || "—"}</p>
                  {ads.data.enabled && ads.data.label ? (
                    <div className="mt-3 rounded-lg border border-warning bg-warning-soft p-3 text-sm">
                      <p className="text-xs font-semibold uppercase tracking-wider text-warning">Ad slot</p>
                      <p className="mt-1 text-muted">{ads.data.label}</p>
                      {ads.data.html ? (
                        <div
                          className="mt-2 rounded bg-white p-2 text-xs"
                          dangerouslySetInnerHTML={{ __html: ads.data.html }}
                        />
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <p className="text-xs text-muted">
                  Ads are served only when a provider is configured and the platform advertising
                  setting is on. Nothing from the model context reaches an ad provider.
                </p>
              </div>
            ) : (
              <div className="py-6 text-sm text-muted">Advertising configuration unavailable.</div>
            )}
          </Card>
        ) : null}
      </div>
    </div>
  );
}
