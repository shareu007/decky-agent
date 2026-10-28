import type { Bootstrap, Session } from "./types";

export type SessionSnapshot = Session | { id: string; revision: number; unchanged: true };

interface SessionReader {
  bootstrap(): Promise<Bootstrap>;
  snapshot(id: string, revision: number): Promise<SessionSnapshot>;
}

// Global task state changes independently of the conversation being viewed.
export async function readSessionState(client: SessionReader, selected: string, revision: number) {
  const data = await client.bootstrap();
  if (!data.sessions.some(session => session.id === selected)) {
    return { data, selected: data.active_id || data.sessions[0]?.id || null, snapshot: null };
  }
  const snapshot = await client.snapshot(selected, revision);
  return { data, selected, snapshot };
}
