import type { AccountStatus, Session, Settings } from "../types";

let settings: Settings = {
  language: "zh-CN",
  engine: "codex", base_url: "https://api.openai.com/v1", model: "my-coding-model",
  auth_mode: "api", chatgpt_model: "",
  api_key_set: false, workspace: "/home/deck/decky-agent-workspace", codex_path: "",
  allow_shell: false, network_access: false, instructions: "请用中文交流。先检查工作目录，再完成任务并验证结果。", max_steps: 20,
  permission_mode: "ask",
  speech_enabled: false, speech_base_url: "", speech_model: "gpt-transcribe", speech_api_key_set: false,
};
const sessions: Session[] = [];
let active: string | null = null;
let recording: { id: string; started: number } | null = null;
let auth: AccountStatus = { phase: "unknown", busy: false, signed_in: false, account: null, login: null, error: "" };
function create(): Session {
  const session: Session = { id: crypto.randomUUID(), title: "新会话", engine: settings.engine,
    status: "idle", auth_mode: settings.auth_mode, model: settings.auth_mode === "chatgpt" ? settings.chatgpt_model : settings.model, items: [], pending: [], revision: 0,
    workspace: settings.workspace, base_url: settings.base_url };
  sessions.unshift(session); return structuredClone(session);
}

export function seedChat(language: Settings["language"] = "zh-CN", chatgpt = false) {
  if (sessions.length) return;
  settings.language = language;
  if (chatgpt) {
    settings.auth_mode = "chatgpt";
    auth = { phase: "signed_in", busy: false, signed_in: true, account: { email: "preview@example.com", plan: "preview" }, login: null, error: "" };
  }
  create();
  if (chatgpt) sessions[0].resolved_model = "codex-default";
  sessions[0].title = "软件更新测试";
  sessions[0].items = [
    { id: "user", role: "user", text: "帮我检查软件更新，先列出待更新的项目。", title: "" },
    { id: "agent", role: "assistant", text: "我会先检查设备环境和可用更新。\n\n1. 确认系统版本\n2. 检查 Flatpak 更新\n3. 列出可以更新的软件\n4. 等待你确认安装范围\n\n有权限请求时，会在对话中显示审批。", title: "" },
  ];
}

export function callable<Args extends unknown[], Result>(name: string): (...args: Args) => Promise<Result> {
  return async (...args) => {
    const session = sessions.find(s => s.id === args[0]);
    let result: unknown;
    switch (name) {
      case "report_frontend": break;
      case "get_bootstrap": result = { settings, sessions, active_id: active, codex_available: true,
        speech: { available: true, busy: !!recording, max_seconds: 60 }, auth }; break;
      case "get_account_status":
        if (auth.phase === "unknown") auth.phase = "signed_out";
        result = auth; break;
      case "login_chatgpt": {
        const id = crypto.randomUUID();
        auth = { phase: "waiting", busy: true, signed_in: false, account: null,
          login: { id, url: "https://auth.openai.com/codex/device", code: "MOCK-1234" }, error: "浏览器预览：模拟授权，无需访问登录页。" };
        setTimeout(() => { if (auth.login?.id === id) auth = { phase: "signed_in", busy: false, signed_in: true, login: null,
          account: { email: "preview@example.com", plan: "preview" }, error: "" }; }, 6000);
        result = auth; break;
      }
      case "cancel_chatgpt_login":
        if (auth.login?.id === args[0]) auth = { phase: "signed_out", busy: false, signed_in: false, account: null, login: null, error: "" };
        result = auth; break;
      case "logout_chatgpt":
        auth = { phase: "signed_out", busy: false, signed_in: false, account: null, login: null, error: "" }; result = auth; break;
      case "create_session": result = create(); break;
      case "delete_session": sessions.splice(sessions.findIndex(s => s.id === args[0]), 1); break;
      case "get_session":
        if (!session) throw new Error("会话不存在");
        result = session.revision === args[1] ? { id: session.id, unchanged: true, revision: args[1] } : session; break;
      case "save_settings": {
        const changes = args[0] as Record<string, unknown>;
        settings = { ...settings, ...changes, api_key_set: changes.clear_api_key ? false : !!changes.api_key || settings.api_key_set } as Settings;
        delete (settings as unknown as Record<string, unknown>).api_key;
        settings.speech_api_key_set = changes.clear_speech_api_key ? false : !!changes.speech_api_key || settings.speech_api_key_set;
        delete (settings as unknown as Record<string, unknown>).speech_api_key;
        result = settings; break;
      }
      case "list_models": result = settings.auth_mode === "chatgpt" ? ["codex-default", "preview-model"] : ["my-coding-model", "local-coder", "custom-model"]; break;
      case "get_model_catalog": result = [{ model: "codex-default", display_name: "Codex Default", is_default: true }, { model: "preview-model", display_name: "Preview Model", is_default: false }]; break;
      case "start_task": {
        if (!session) throw new Error("会话不存在");
        if (!session.items.length) { session.auth_mode = settings.auth_mode; session.model = settings.auth_mode === "chatgpt" ? settings.chatgpt_model : settings.model; }
        active = session.id; session.status = "waiting"; session.title = String(args[1]).slice(0, 28);
        session.items.push({ id: crypto.randomUUID(), role: "user", text: String(args[1]), title: "" });
        session.items.push({ id: crypto.randomUUID(), role: "assistant", text: "这是浏览器预览中的模拟任务。我将先检查工作目录中的项目结构。", title: "" });
        session.pending = [{ id: "preview-approval", kind: "approval", title: "Codex 请求操作授权", detail: "工作目录：/home/deck/decky-agent-workspace\n\n$ find . -maxdepth 2 -type f\n\n此操作只用于浏览器界面预览，不会执行真实命令。", questions: [] }];
        session.revision++; result = session; break;
      }
      case "respond_request":
        if (session) { session.pending = []; session.status = "completed"; session.items.push({ id: crypto.randomUUID(), role: "assistant", title: "", text: args[2] ? "模拟任务已完成。正式插件会在这里显示模型的流式回复和工具执行结果。" : "你拒绝了这次操作。" }); session.revision++; active = null; }
        break;
      case "stop_task": if (session) { session.status = "cancelled"; session.pending = []; session.revision++; active = null; } break;
      case "start_recording":
        if (!settings.speech_enabled) throw new Error("请先在设置 → 高级设置中启用语音输入");
        if (recording) throw new Error("已有录音正在进行");
        recording = { id: crypto.randomUUID(), started: Date.now() };
        result = { id: recording.id, state: "recording", seconds: 0 }; break;
      case "recording_status":
        if (!recording || recording.id !== args[0]) throw new Error("录音已结束");
        result = { id: recording.id, state: Date.now() - recording.started < 60000 ? "recording" : "ready", seconds: Math.min(60, Math.floor((Date.now() - recording.started) / 1000)) }; break;
      case "finish_recording":
        if (!recording || recording.id !== args[0]) throw new Error("录音已结束");
        await new Promise(resolve => setTimeout(resolve, 800));
        recording = null; result = "这是一段模拟语音转写，请帮我检查当前项目。"; break;
      case "cancel_recording": recording = null; break;
      default: throw new Error(`Unknown preview method: ${name}`);
    }
    return structuredClone(result) as Result;
  };
}

export const definePlugin = (factory: () => unknown) => factory;
