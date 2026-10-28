import test from "node:test";
import assert from "node:assert/strict";
import { readSessionState } from "../src/polling.ts";
import type { Bootstrap } from "../src/types.ts";
import type { Session } from "../src/types.ts";
import { configurationSessionAction } from "../src/settings-state.ts";

const bootstrap = (active: string | null): Bootstrap => ({
  settings: { language: "zh-CN", engine: "codex", base_url: "http://localhost/v1", model: "test", api_key_set: false,
    auth_mode: "api", chatgpt_model: "",
    permission_mode: "ask",
    workspace: "/tmp/test", codex_path: "", allow_shell: false, network_access: false, instructions: "", max_steps: 20,
    speech_enabled: false, speech_base_url: "", speech_model: "gpt-transcribe", speech_api_key_set: false },
  sessions: [{ id: "idle", title: "Idle", engine: "codex", model: "test", status: "idle" },
    { id: "other", title: "Other", engine: "codex", model: "test", status: active ? "running" : "completed" }],
  active_id: active, codex_available: true, speech: { available: false, busy: false, max_seconds: 60 },
  auth: { phase: "signed_out", busy: false, signed_in: false, account: null, login: null, error: "" },
});

test("global task state refreshes when the selected conversation is unchanged", async () => {
  let active: string | null = "other";
  const client = { bootstrap: async () => bootstrap(active), snapshot: async (id: string, revision: number) => ({ id, revision, unchanged: true as const }) };
  const running = await readSessionState(client, "idle", 3);
  assert.equal(running.data.active_id, "other");
  active = null;
  const completed = await readSessionState(client, "idle", 3);
  assert.equal(completed.data.active_id, null);
  assert.equal(completed.data.sessions[1].status, "completed");
});

test("deleted conversations fall back to the active task without stale snapshot requests", async () => {
  const state = await readSessionState({ bootstrap: async () => bootstrap("other"), snapshot: async () => { throw new Error("stale request"); } }, "deleted", 4);
  assert.equal(state.selected, "other");
  assert.equal(state.snapshot, null);
});

const conversation = (): Session => ({
  ...bootstrap(null).sessions[0], auth_mode: "api", workspace: "/tmp/test", base_url: "http://localhost/v1", pending: [], revision: 1,
  items: [{ id: "user", role: "user", text: "previous task", title: "" }],
});

test("saving unchanged settings reuses the conversation even at the history limit", () => {
  assert.equal(configurationSessionAction(conversation(), bootstrap(null).settings, 30), "reuse");
});

test("changing permission mode keeps the existing conversation for native thread overrides", () => {
  assert.equal(configurationSessionAction(conversation(), { ...bootstrap(null).settings, permission_mode: "auto" }, 30), "reuse");
  assert.equal(configurationSessionAction(conversation(), { ...bootstrap(null).settings, permission_mode: "full" }, 30), "reuse");
});

test("changing provider context creates a conversation or reports capacity explicitly", () => {
  const saved = { ...bootstrap(null).settings, base_url: "http://different/v1" };
  assert.equal(configurationSessionAction(conversation(), saved, 29), "create");
  assert.equal(configurationSessionAction(conversation(), saved, 30), "capacity");
});

test("an unused conversation can adopt new settings without consuming history capacity", () => {
  const empty = { ...conversation(), items: [] };
  assert.equal(configurationSessionAction(empty, { ...bootstrap(null).settings, model: "different" }, 30), "reuse");
});

test("switching from API to ChatGPT cannot reuse a populated provider conversation", () => {
  const saved = { ...bootstrap(null).settings, auth_mode: "chatgpt" as const };
  assert.equal(configurationSessionAction(conversation(), saved, 2), "create");
});

test("ChatGPT conversation comparisons use the independent ChatGPT model", () => {
  const saved = { ...bootstrap(null).settings, auth_mode: "chatgpt" as const, chatgpt_model: "", model: "old-api-model" };
  const current = { ...conversation(), auth_mode: "chatgpt" as const, model: "" };
  assert.equal(configurationSessionAction(current, saved, 2), "reuse");
  assert.equal(configurationSessionAction(current, { ...saved, chatgpt_model: "other" }, 30), "reuse");
});

test("compatible API model changes still require a fresh conversation", () => {
  const current = { ...conversation(), engine: "compatible" as const };
  const settings = { ...bootstrap(null).settings, engine: "compatible" as const, model: "other" };
  assert.equal(configurationSessionAction(current, settings, 29), "create");
  assert.equal(configurationSessionAction(current, settings, 30), "capacity");
});

test("language changes reuse conversation and retain the existing model configuration", () => {
  assert.equal(configurationSessionAction(conversation(), { ...bootstrap(null).settings, language: "en" }, 30), "reuse");
});
