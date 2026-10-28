import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { SpeechController } from "./speech-state";
import type { SpeechState } from "./speech-state";

export function useSpeech(sessionId: string | null, onTranscript: (text: string) => void, onError: (message: string) => void) {
  const callbacks = useRef({ onTranscript, onError });
  callbacks.current = { onTranscript, onError };
  const mounted = useRef(true);
  const [state, setState] = useState<SpeechState>({ phase: "idle", seconds: 0 });
  const [controller] = useState(() => new SpeechController(api,
    next => { if (mounted.current) setState(next); },
    text => { if (mounted.current) callbacks.current.onTranscript(text); },
    message => { if (mounted.current) callbacks.current.onError(message); },
  ));
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; void controller.cancel(true); };
  }, [controller]);
  useEffect(() => () => { void controller.cancel(true); }, [controller, sessionId]);
  useEffect(() => {
    if (!["recording", "ready"].includes(state.phase)) return;
    const timer = setInterval(() => void controller.refresh(), 500);
    return () => clearInterval(timer);
  }, [controller, state.phase]);
  return { ...state, busy: state.phase !== "idle", start: () => sessionId && controller.start(sessionId),
    finish: () => controller.finish(), cancel: () => controller.cancel() };
}
