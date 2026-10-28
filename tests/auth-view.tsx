import test from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { ConnectionSettings } from "../src/Settings";
import type { AccountStatus, Settings } from "../src/types";
import type { AgentController } from "../src/api";
import { ModelPicker } from "../src/ModelPicker";
import { Composer } from "../src/components";
import { LocaleProvider } from "../src/locale";

const settings: Settings = {
  language: "zh-CN",
  engine: "codex", auth_mode: "chatgpt", chatgpt_model: "", model: "saved-api-model",
  permission_mode: "ask",
  base_url: "https://api.example.com/v1", api_key_set: true, workspace: "/home/deck/project",
  codex_path: "", allow_shell: false, network_access: false, instructions: "", max_steps: 20,
  speech_enabled: false, speech_base_url: "", speech_model: "gpt-transcribe", speech_api_key_set: false,
};
const signedOut: AccountStatus = { phase: "signed_out", signed_in: false, busy: false, account: null, login: null, error: "" };
function render(auth: AccountStatus, config = settings) {
  const agent = { data: { settings: config, auth, active_id: null, sessions: [], codex_available: true, speech: { busy: false } },
    working: false, session: { id: "test", items: [] }, error: "" } as unknown as AgentController;
  return renderToStaticMarkup(<ConnectionSettings agent={agent} onSaved={() => {}} />);
}

test("ChatGPT sign-in shows device-login entry and hides API credentials", () => {
  const html = render(signedOut);
  assert.match(html, /登录 ChatGPT/);
  assert.match(html, /aria-label="模型"/);
  assert.match(html, /自动选择/);
  assert.doesNotMatch(html, /aria-label="API Key"|aria-label="API 地址"/);
  assert.doesNotMatch(html, /api\.example\.com|saved-api-model/);
});

test("pending authorization shows official URL, code and cancellation in the panel", () => {
  const html = render({ ...signedOut, phase: "waiting", busy: true,
    login: { id: "test-id", url: "https://auth.openai.com/codex/device", code: "TEST-1234" } });
  assert.match(html, /auth\.openai\.com\/codex\/device/);
  assert.match(html, /TEST-1234/);
  assert.match(html, /取消登录/);
  assert.doesNotMatch(html, /aria-label="API Key"/);
});

test("signed-in account shows account and logout while dropping the expired device code", () => {
  const html = render({ ...signedOut, phase: "signed_in", signed_in: true, account: { email: "test@example.com", plan: "plus" } });
  assert.match(html, /test@example\.com/);
  assert.match(html, /退出登录/);
  assert.doesNotMatch(html, /设备授权码|取消登录/);
});

test("API mode retains the saved API connection and independent model", () => {
  const html = render(signedOut, { ...settings, auth_mode: "api" });
  assert.match(html, /aria-label="API Key"/);
  assert.match(html, /api\.example\.com/);
  assert.match(html, /saved-api-model/);
  assert.doesNotMatch(html, /设备授权码/);
});

test("English settings translate connection and permission controls and offer both languages", () => {
  const html = render({ ...signedOut, phase: "signed_in", signed_in: true, account: { email: "test@example.com", plan: "plus" } }, { ...settings, language: "en" });
  assert.match(html, /Interface language/);
  assert.match(html, /English/);
  assert.match(html, /中文/);
  assert.match(html, /Sign out/);
  assert.match(html, /aria-label="Model"/);
  assert.match(html, /Ask me/);
  assert.match(html, /Auto review/);
  assert.doesNotMatch(html, /权限模式|请求批准|退出登录|工作目录|模型来自|按账号/);
});

test("model selector shows Codex names, the actual default and a saved unlisted model", () => {
  const html = renderToStaticMarkup(<LocaleProvider language="en"><ModelPicker value="saved-unlisted-model" resolved="actual-default-model"
    catalog={{ models: [{ model: "real-slug", display_name: "Readable Model", is_default: true }], loading: false, error: "", reload: async () => {} }} onChange={() => {}} /></LocaleProvider>);
  assert.match(html, /Auto · actual-default-model/);
  assert.match(html, /value="real-slug">Readable Model/);
  assert.match(html, /value="saved-unlisted-model" selected="">saved-unlisted-model/);
  assert.match(html, /Refresh models/);
});

test("signed-in chat composer includes model and permissions in both interface languages", () => {
  for (const language of ["zh-CN", "en"] as const) {
    const agent = { data: { settings: { ...settings, language }, auth: { ...signedOut, phase: "signed_in", signed_in: true }, speech: { busy: false }, active_id: null },
      selected: "test", session: { id: "test", model: "", resolved_model: "actual-codex", status: "idle", items: [], workspace: "/project" }, working: false } as unknown as AgentController;
    const html = renderToStaticMarkup(<LocaleProvider language={language}><Composer agent={agent} draft="keep my draft" setDraft={() => {}} /></LocaleProvider>);
    assert.match(html, /actual-codex/);
    assert.match(html, /keep my draft/);
    assert.match(html, language === "en" ? /aria-label="Model"/ : /aria-label="模型"/);
    assert.match(html, language === "en" ? /Ask me/ : /请求批准/);
    assert.match(html, language === "en" ? /Describe a task/ : /输入任务/);
  }
});
