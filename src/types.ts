export type PermissionMode = "ask" | "auto" | "full";
export type Language = "zh-CN" | "en";
export interface ModelOption { model: string; display_name: string; is_default: boolean }
export interface Settings {
  language: Language;
  engine: "codex" | "compatible";
  auth_mode: "api" | "chatgpt";
  chatgpt_model: string;
  base_url: string;
  model: string;
  api_key_set: boolean;
  workspace: string;
  codex_path: string;
  allow_shell: boolean;
  network_access: boolean;
  permission_mode: PermissionMode;
  instructions: string;
  max_steps: number;
  speech_enabled: boolean;
  speech_base_url: string;
  speech_model: string;
  speech_api_key_set: boolean;
}

export interface AgentItem {
  id: string;
  role: "user" | "assistant" | "tool" | "system";
  text: string;
  title: string;
  status?: string;
}

export interface PendingRequest {
  id: string;
  kind: "approval" | "input";
  title: string;
  detail: string;
  questions: { id: string; header: string; question: string; options?: { label: string; description: string }[] }[];
}

export interface SessionSummary {
  id: string;
  title: string;
  engine: Settings["engine"];
  status: string;
  model: string;
}

export interface Session extends SessionSummary {
  resolved_model?: string;
  permission_mode?: PermissionMode;
  started_at?: number | null;
  progress?: string;
  auth_mode: Settings["auth_mode"];
  items: AgentItem[];
  pending: PendingRequest[];
  revision: number;
  workspace: string;
  base_url: string;
}

export interface Bootstrap {
  settings: Settings;
  sessions: SessionSummary[];
  active_id: string | null;
  codex_available: boolean;
  speech: { available: boolean; busy: boolean; max_seconds: number };
  auth: AccountStatus;
}

export interface AccountStatus {
  busy: boolean;
  phase: "unknown" | "checking" | "starting" | "waiting" | "signed_in" | "signed_out" | "error";
  signed_in: boolean;
  account: { email: string; plan: string } | null;
  login: { id: string; url: string; code: string } | null;
  error: string;
}

export interface RecordingStatus {
  id: string;
  state: "recording" | "ready" | "failed" | "transcribing";
  seconds: number;
}
