import test from "node:test";
import assert from "node:assert/strict";
import { appendTranscript, SpeechController } from "../src/speech-state.ts";
import type { SpeechTransport } from "../src/speech-state.ts";
import type { RecordingStatus } from "../src/types.ts";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (cause: unknown) => void;
  const promise = new Promise<T>((accept, decline) => { resolve = accept; reject = decline; });
  return { promise, resolve, reject };
}

function setup(overrides: Partial<SpeechTransport> = {}) {
  const texts: string[] = [];
  const errors: string[] = [];
  const cancelled: string[] = [];
  const transport: SpeechTransport = {
    startRecording: async () => ({ id: "mic", state: "recording", seconds: 0 }),
    recordingStatus: async () => ({ id: "mic", state: "ready", seconds: 60 }),
    finishRecording: async () => "识别文字",
    cancelRecording: async id => { cancelled.push(id); }, ...overrides,
  };
  const controller = new SpeechController(transport, () => {}, text => texts.push(text), error => errors.push(error));
  return { controller, texts, errors, cancelled };
}

test("speech fills a draft and requires a separate send action", async () => {
  const { controller, texts } = setup();
  await controller.start("session");
  assert.equal(controller.state.phase, "recording");
  await controller.finish();
  assert.deepEqual(texts, ["识别文字"]);
  assert.equal(controller.state.phase, "idle");
  assert.equal(appendTranscript("原有任务 ", texts[0]), "原有任务 识别文字");
});

test("a recording that starts after navigation is immediately cancelled", async () => {
  const started = deferred<RecordingStatus>();
  const { controller, cancelled } = setup({ startRecording: () => started.promise });
  const pending = controller.start("old-session");
  await controller.cancel();
  started.resolve({ id: "late-mic", state: "recording", seconds: 0 });
  await pending;
  assert.deepEqual(cancelled, ["late-mic"]);
  assert.equal(controller.state.phase, "idle");
});

test("cancelled transcription never fills another conversation", async () => {
  const result = deferred<string>();
  const { controller, texts, cancelled } = setup({ finishRecording: () => result.promise });
  await controller.start("old-session");
  const pending = controller.finish();
  await controller.cancel();
  result.resolve("old transcript");
  await pending;
  assert.deepEqual(texts, []);
  assert.deepEqual(cancelled, ["mic"]);
});

test("late recording status cannot revive a finished recording", async () => {
  const status = deferred<RecordingStatus>();
  const { controller } = setup({ recordingStatus: () => status.promise });
  await controller.start("session");
  const poll = controller.refresh();
  await controller.finish();
  status.resolve({ id: "mic", state: "ready", seconds: 60 });
  await poll;
  assert.equal(controller.state.phase, "idle");
});

test("a late recording poll failure cannot cancel transcription or lose its text", async () => {
  const status = deferred<RecordingStatus>();
  const result = deferred<string>();
  const { controller, texts, errors, cancelled } = setup({
    recordingStatus: () => status.promise,
    finishRecording: () => result.promise,
  });
  await controller.start("session");
  const poll = controller.refresh();
  const finish = controller.finish();
  status.reject(new Error("录音已结束或已过期，请重新录音"));
  await poll;
  assert.equal(controller.state.phase, "transcribing");
  result.resolve("停止后应填入输入框的文字");
  await finish;
  assert.deepEqual(texts, ["停止后应填入输入框的文字"]);
  assert.deepEqual(errors, []);
  assert.deepEqual(cancelled, []);
});

test("a late poll failure after successful transcription cannot replace the result with an error", async () => {
  const status = deferred<RecordingStatus>();
  const { controller, texts, errors, cancelled } = setup({ recordingStatus: () => status.promise });
  await controller.start("session");
  const poll = controller.refresh();
  await controller.finish();
  status.reject({ message: "录音已结束" });
  await poll;
  assert.deepEqual(texts, ["识别文字"]);
  assert.deepEqual(errors, []);
  assert.deepEqual(cancelled, []);
});

test("Decky error objects show their actionable message instead of object Object", async () => {
  const { controller, errors, texts } = setup({ finishRecording: async () => {
    throw { name: "TLSVerificationError", message: "无法验证服务的 HTTPS 证书，请检查系统证书和设备时间后重试" };
  } });
  await controller.start("session");
  await controller.finish();
  assert.match(errors[0], /HTTPS 证书/);
  assert.equal(controller.state.phase, "idle");
  assert.deepEqual(texts, []);
});

test("empty transcription cannot silently return to idle", async () => {
  const { controller, errors, texts } = setup({ finishRecording: async () => "  " });
  await controller.start("session");
  await controller.finish();
  assert.match(errors[0], /没有识别到文字/);
  assert.deepEqual(texts, []);
});

test("automatic duration limit leaves audio ready until explicit transcription", async () => {
  const { controller, texts } = setup();
  await controller.start("session");
  await controller.refresh();
  assert.equal(controller.state.phase, "ready");
  assert.deepEqual(texts, []);
  await controller.finish();
  assert.deepEqual(texts, ["识别文字"]);
});

test("recording errors cancel the capture and report an actionable message", async () => {
  const { controller, errors, cancelled } = setup({ recordingStatus: async () => ({ id: "mic", state: "failed", seconds: 1 }) });
  await controller.start("session");
  await controller.refresh();
  assert.deepEqual(cancelled, ["mic"]);
  assert.match(errors[0], /麦克风/);
  assert.equal(controller.state.phase, "idle");
});
