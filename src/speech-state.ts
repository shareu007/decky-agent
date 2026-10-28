import type { RecordingStatus } from "./types";

export type SpeechPhase = "idle" | "starting" | "recording" | "ready" | "transcribing" | "cancelling";
export interface SpeechState { phase: SpeechPhase; seconds: number }
export interface SpeechTransport {
  startRecording(sessionId: string): Promise<RecordingStatus>;
  recordingStatus(id: string): Promise<RecordingStatus>;
  finishRecording(id: string): Promise<string>;
  cancelRecording(id: string): Promise<void>;
}

export function appendTranscript(draft: string, text: string): string {
  return [draft.trimEnd(), text.trim()].filter(Boolean).join(" ");
}

// Generation checks discard late RPC results after navigation or cancellation.
export class SpeechController {
  state: SpeechState = { phase: "idle", seconds: 0 };
  private generation = 0;
  private ticket: string | null = null;
  private refreshing = false;
  private transport: SpeechTransport;
  private changed: (state: SpeechState) => void;
  private transcript: (text: string) => void;
  private error: (message: string) => void;

  constructor(transport: SpeechTransport, changed: (state: SpeechState) => void,
    transcript: (text: string) => void, error: (message: string) => void) {
    this.transport = transport; this.changed = changed; this.transcript = transcript; this.error = error;
  }

  private update(phase: SpeechPhase, seconds = this.state.seconds) {
    this.state = { phase, seconds };
    this.changed(this.state);
  }

  private fail(cause: unknown) {
    // Decky's WebSocket rejects with { name, message }, not always an Error.
    const message = cause && typeof cause === "object" && "message" in cause ? cause.message : cause;
    this.error(typeof message === "string" && message.trim() ? message : "语音输入失败，请重试");
  }

  async start(sessionId: string) {
    if (this.state.phase !== "idle") return;
    const version = ++this.generation;
    this.update("starting", 0);
    try {
      const status = await this.transport.startRecording(sessionId);
      if (version !== this.generation) {
        await this.transport.cancelRecording(status.id);
        return;
      }
      this.ticket = status.id;
      this.update("recording", status.seconds);
    } catch (cause) {
      if (version === this.generation) { this.update("idle", 0); this.fail(cause); }
    }
  }

  async refresh() {
    if (this.refreshing || !this.ticket || !["recording", "ready"].includes(this.state.phase)) return;
    this.refreshing = true;
    const version = this.generation;
    const id = this.ticket;
    try {
      const status = await this.transport.recordingStatus(id);
      if (version !== this.generation || !["recording", "ready"].includes(this.state.phase)) return;
      if (status.state === "failed") throw new Error("录音失败，请检查默认麦克风和音频权限");
      this.update(status.state === "ready" ? "ready" : "recording", status.seconds);
    } catch (cause) {
      // A poll can fail after finish() has already stopped/deleted the capture.
      // Its failure belongs to recording, never to the newer transcription.
      if (version === this.generation && ["recording", "ready"].includes(this.state.phase)) {
        await this.cancel(true); if (this.generation === version + 1) this.fail(cause);
      }
    } finally { this.refreshing = false; }
  }

  async finish() {
    if (!this.ticket || !["recording", "ready"].includes(this.state.phase)) return;
    const version = this.generation;
    const id = this.ticket;
    this.update("transcribing");
    try {
      const text = await this.transport.finishRecording(id);
      if (version !== this.generation) return;
      if (typeof text !== "string" || !text.trim()) throw new Error("没有识别到文字，请检查麦克风并重试");
      this.ticket = null;
      this.update("idle", 0);
      this.transcript(text);
    } catch (cause) {
      if (version === this.generation) { this.ticket = null; this.update("idle", 0); this.fail(cause); }
    }
  }

  async cancel(silent = false) {
    const version = ++this.generation;
    const id = this.ticket;
    this.ticket = null;
    this.update(id ? "cancelling" : "idle", 0);
    try { if (id) await this.transport.cancelRecording(id); }
    catch (cause) { if (!silent) this.fail(cause); }
    finally { if (version === this.generation) this.update("idle", 0); }
  }
}
