/** Types mirroring the Bozii REST API schemas. */

export type TaskState =
  | "queued"
  | "planning"
  | "running"
  | "waiting_approval"
  | "recovering"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export interface User {
  id: string;
  email: string;
  name: string;
  role: string;
  created_at: string;
}

export interface Employee {
  id: string;
  name: string;
  slug: string;
  role: string;
  description: string;
  system_prompt: string;
  template_key: string | null;
  avatar_seed: string;
  avatar_color: string;
  model_id: string | null;
  model_name: string;
  temperature: number;
  status: "active" | "paused" | "archived";
  memory_enabled: boolean;
  permissions: Record<string, unknown>;
  tools_allowlist: string[];
  tools_denylist: string[];
  max_iterations: number;
  timeout_seconds: number;
  created_at: string;
  updated_at: string;
  last_active_at: string | null;
  active_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
}

export interface EmployeeTemplate {
  key: string;
  name: string;
  role: string;
  description: string;
  avatar_color: string;
}

export interface MemoryEntry {
  id: string;
  employee_id: string;
  kind: string;
  key: string;
  content: string;
  pinned: boolean;
  source_task_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskEvent {
  id: string;
  task_id: string;
  seq: number;
  type: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface SubTask {
  id: string;
  title: string;
  description: string;
  status: "pending" | "running" | "done" | "failed" | "skipped";
  order_index: number;
  assignee_employee_id: string | null;
  output: string;
  created_at: string;
}

export interface Approval {
  id: string;
  task_id: string;
  employee_id: string | null;
  kind: string;
  title: string;
  description: string;
  payload: Record<string, unknown>;
  state: "pending" | "approved" | "denied";
  reason: string | null;
  created_at: string;
  decided_at: string | null;
}

export interface Artifact {
  id: string;
  user_id: string;
  task_id: string | null;
  employee_id: string | null;
  name: string;
  kind: string;
  relative_path: string;
  mime_type: string;
  size: number;
  sha256: string;
  created_at: string;
}

export interface Task {
  id: string;
  user_id: string;
  employee_id: string;
  team_id: string | null;
  parent_task_id: string | null;
  title: string;
  objective: string;
  state: TaskState;
  priority: number;
  plan: { index: number; title: string; description: string; status: string }[];
  result: Record<string, unknown>;
  report: string;
  error: string | null;
  approval_needed: boolean;
  attempt: number;
  max_iterations: number;
  iterations_used: number;
  tool_calls: number;
  delegation_depth: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
  employee_name: string | null;
}

export interface TaskDetail extends Task {
  subtasks: SubTask[];
  events: TaskEvent[];
  approvals: Approval[];
  artifacts: Artifact[];
  employee_name: string;
  messages: ChatMessage[];
}

export interface TaskListEntry extends Task {
  employee_name: string | null;
}

export interface ChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  name?: string;
  tool_call_id?: string;
  tool_calls?: { id: string; function: { name: string; arguments: string } }[];
}

export interface Tool {
  name: string;
  title: string;
  description: string;
  category: string;
  kind: "builtin" | "capability";
  risk: "safe" | "mutating" | "consequential";
  required_permissions: Record<string, unknown>;
  parameters: { properties?: Record<string, { type?: string; description?: string; enum?: string[] }> };
  enabled: boolean;
  version: string;
  capability_id: string | null;
}

export interface Capability {
  id: string;
  slug: string;
  name: string;
  kind: "tool" | "skill";
  version: number;
  status: "draft" | "validating" | "active" | "disabled" | "deprecated" | "failed";
  category: string;
  description: string;
  tags: string[];
  manifest: Record<string, unknown>;
  input_schema: Record<string, unknown>;
  permissions: string[];
  dependencies: string[];
  test_results: Record<string, unknown>;
  scan_results: { passed?: boolean; findings?: { level: string; rule: string; detail: string; file: string; line: number }[] };
  provenance: Record<string, unknown>;
  checksum: string;
  is_active: boolean;
  visibility: "private" | "public";
  downloads: number;
  reports: number;
  created_by_employee_id: string | null;
  source_task_id: string | null;
  created_at: string;
  activated_at: string | null;
  tests_passed?: boolean;
  scan_findings?: number;
}

export interface TeamMember {
  id: string;
  team_id: string;
  employee_id: string;
  role: string;
  created_at: string;
  employee_name: string;
}

export interface Team {
  id: string;
  name: string;
  description: string;
  objective: string;
  lead_employee_id: string | null;
  created_at: string;
  members: TeamMember[];
  task_count: number;
}

export interface TeamMessage {
  id: string;
  team_id: string | null;
  from_employee_id: string | null;
  to_employee_id: string | null;
  task_id: string | null;
  content: string;
  kind: string;
  created_at: string;
}

export interface ModelInfo {
  id: string;
  provider_id: string;
  name: string;
  display_name: string;
  context_window: number | null;
  capabilities: string[];
  available: boolean;
  is_default: boolean;
  discovered_at: string;
}

export interface Provider {
  id: string;
  name: string;
  kind: "ollama" | "openai_compat" | "mock";
  base_url: string;
  api_key_env: string;
  enabled: boolean;
  is_default: boolean;
  config: Record<string, unknown>;
  created_at: string;
  last_health_at: string | null;
  last_health_ok: boolean | null;
  last_health_error: string | null;
  has_api_key: boolean;
  models: ModelInfo[];
}

export interface DashboardStats {
  employees: number;
  active_tasks: number;
  queued_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  cancelled_tasks: number;
  waiting_approval: number;
  artifacts: number;
  capabilities: number;
  public_capabilities: number;
  tools: number;
  providers_ok: number;
  providers_total: number;
  tokens_used: number;
  tasks_last_7d: number;
}

export interface ActivityItem {
  id: string;
  source: "audit" | "task_event";
  actor: string;
  action: string;
  message: string;
  resource_type: string;
  resource_id: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface SandboxReport {
  network_isolation: boolean;
  privilege_drop: boolean;
  sandbox_user: string | null;
  running_as_root: boolean;
  timeout_seconds: number;
  memory_mb: number;
  cpu_seconds: number;
  allowed_commands: string[];
  notes: string;
}

export interface AppSettings {
  app_name: string;
  environment: string;
  allow_signup: boolean;
  enable_ads: boolean;
  ads_configured: boolean;
  ads_placement: string;
  ads_provider: string;
  task_workers: number;
  max_iterations: number;
  task_timeout_seconds: number;
  sandbox: SandboxReport;
  version: string;
  needs_setup: boolean;
}

export interface AdsPayload {
  enabled: boolean;
  placement: string;
  provider: string;
  label: string;
  html: string;
}
