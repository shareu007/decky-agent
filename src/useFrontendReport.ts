import { useEffect } from "react";
import type { RefObject } from "react";
import { api } from "./api";
import { FRONTEND_VERSION } from "./version";

// Only report this plugin's dimensions and build. No chat or account content.
// Steam renders plugin content in a different window from SharedJSContext.
export function useFrontendReport(ref: RefObject<HTMLDivElement | null>, ready: boolean) {
  useEffect(() => {
    if (!ready) return;
    const timer = setTimeout(() => {
      const panel = ref.current;
      const view = panel?.ownerDocument.defaultView;
      const messages = panel?.querySelector(".da-scroll");
      if (!panel || !view || !messages) return;
      const box = panel.getBoundingClientRect();
      const chat = messages.getBoundingClientRect();
      let top = Math.max(0, chat.top);
      let bottom = Math.min(view.innerHeight, chat.bottom);
      for (let parent = messages.parentElement; parent; parent = parent.parentElement) {
        if (/(hidden|clip|auto|scroll)/.test(view.getComputedStyle(parent).overflowY)) {
          const clip = parent.getBoundingClientRect();
          top = Math.max(top, clip.top); bottom = Math.min(bottom, clip.bottom);
        }
      }
      void api.reportFrontend({ version: FRONTEND_VERSION, same_window: view === window,
        viewport_height: view.innerHeight, global_viewport_height: window.innerHeight,
        panel_top: box.top, panel_height: box.height, messages_height: chat.height,
        visible_messages_height: Math.max(0, bottom - top),
        composer_height: panel.querySelector(".da-composer")?.getBoundingClientRect().height || 0,
      }).catch(() => {});
    }, 1000);
    return () => clearTimeout(timer);
  }, [ref, ready]);
}
