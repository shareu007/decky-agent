import type { Session, Settings } from "./types";

export const connectionModel = (settings?: Settings) => settings?.auth_mode === "chatgpt" ? settings.chatgpt_model : settings?.model;

export function configurationSessionAction(current: Session | null, saved: Settings, sessionCount: number) {
  if (current && (current.items.length === 0 || (
    ["engine", "auth_mode", "base_url", "workspace"] as const
  ).every(key => current[key] === saved[key]) && (current.engine === "codex" || current.model === connectionModel(saved)))) return "reuse";
  return sessionCount >= 30 ? "capacity" : "create";
}
