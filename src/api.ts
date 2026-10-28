import { callable } from "@decky/api";
import { useCallback, useEffect, useRef, useState } from "react";
import type { AccountStatus, Bootstrap, ModelOption, RecordingStatus, Session, Settings } from "./types";
import { readSessionState } from "./polling";
import type { SessionSnapshot } from "./polling";

export const api = {
  reportFrontend: callable<[details: Record<string, unknown>], void>("report_frontend"),
  bootstrap: callable<[], Bootstrap>("get_bootstrap"),
  save: callable<[changes: Record<string, unknown>], Settings>("save_settings"),
  models: callable<[], string[]>("list_models"),
  modelCatalog: callable<[], ModelOption[]>("get_model_catalog"),
  account: callable<[], AccountStatus>("get_account_status"),
  login: callable<[], AccountStatus>("login_chatgpt"),
  cancelLogin: callable<[id: string], AccountStatus>("cancel_chatgpt_login"),
  logout: callable<[], AccountStatus>("logout_chatgpt"),
  create: callable<[], Session>("create_session"),
  remove: callable<[id: string], void>("delete_session"),
  snapshot: callable<[id: string, revision: number], SessionSnapshot>("get_session"),
  start: callable<[id: string, prompt: string], Session>("start_task"),
  stop: callable<[id: string], void>("stop_task"),
  respond: callable<[id: string, request: string, approved: boolean, answers: Record<string, string>], void>("respond_request"),
  startRecording: callable<[sessionId: string], RecordingStatus>("start_recording"),
  recordingStatus: callable<[id: string], RecordingStatus>("recording_status"),
  finishRecording: callable<[id: string], string>("finish_recording"),
  cancelRecording: callable<[id: string], void>("cancel_recording"),
};

export const isRunning = (session?: Session | null) => !!session && ["running", "waiting"].includes(session.status);

export function useAgent() {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const mounted = useRef(true);
  const revision = useRef(-1);
  const actionCount = useRef(0);
  const selectedRef = useRef<string | null>(null);

  const selectSession = useCallback((id: string | null) => {
    selectedRef.current = id;
    revision.current = -1;
    setSession(null);
    setSelected(id);
  }, []);

  const acceptBootstrap = useCallback((next: Bootstrap) => {
    setData(current => JSON.stringify(current) === JSON.stringify(next) ? current : next);
  }, []);

  const refresh = useCallback(async () => {
    const next = await api.bootstrap();
    if (mounted.current) acceptBootstrap(next);
    return next;
  }, [acceptBootstrap]);

  const act = useCallback(async (operation: () => Promise<unknown>) => {
    setWorking(true);
    actionCount.current++;
    setError("");
    try {
      await operation();
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      actionCount.current--;
      if (mounted.current) setWorking(actionCount.current > 0);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void act(async () => {
      const initial = await refresh();
      let id = initial.active_id || initial.sessions[0]?.id;
      if (!id) {
        const created = await api.create();
        id = created.id;
        await refresh();
      }
      if (mounted.current) selectSession(id);
    });
    return () => { mounted.current = false; };
  }, [act, refresh, selectSession]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    revision.current = -1;
    setSession(null);
    const poll = async () => {
      try {
        const next = await readSessionState(api, selected, revision.current);
        if (cancelled) return;
        acceptBootstrap(next.data);
        if (next.selected !== selected) {
          if (next.selected) selectSession(next.selected);
          else {
            const created = await api.create();
            if (!cancelled) selectSession(created.id);
          }
          return;
        }
        if (next.snapshot && !("unchanged" in next.snapshot)) {
          revision.current = next.snapshot.revision;
          setSession(next.snapshot);
        }
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      }
      if (!cancelled) timer = setTimeout(() => void poll(), 700);
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [selected, acceptBootstrap, selectSession]);

  const newSession = () => act(async () => {
    const created = await api.create();
    await refresh();
    selectSession(created.id);
  });

  const send = async (prompt: string): Promise<boolean> => {
    if (!selected || !prompt.trim()) return false;
    let sent = false;
    const target = selected;
    await act(async () => {
      const started = await api.start(target, prompt);
      sent = true;
      if (mounted.current && selectedRef.current === target) setSession(started);
      await refresh();
      revision.current = -1;
    });
    return sent;
  };

  return {
    data, session, selected, setSelected: selectSession, error, setError, working, act, refresh,
    newSession, send,
    stop: () => act(async () => { if (selected) await api.stop(selected); revision.current = -1; await refresh(); }),
  };
}

export type AgentController = ReturnType<typeof useAgent>;
