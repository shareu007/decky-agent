import { useEffect, useState } from "react";

// Browser-only geometry check with Steam's native button/input defaults applied.
export function LayoutCheck({ host = false }: { host?: boolean }) {
  const [result, setResult] = useState("正在检查布局…");
  useEffect(() => {
    if (host) {
      const listener = (event: MessageEvent) => {
        if (event.origin === location.origin && event.data?.type === "decky-layout-check") setResult(event.data.text);
      };
      window.addEventListener("message", listener);
      return () => window.removeEventListener("message", listener);
    }
    const timer = setInterval(() => {
      const panel = document.querySelector(".da-panel");
      const messages = document.querySelector(".da-scroll");
      const fields = [...document.querySelectorAll(".da-composer input,.da-composer .da-button")];
      if (!panel || !messages || !fields.length) return;
      const limit = panel.getBoundingClientRect();
      const clip = document.querySelector(".preview-content");
      const bottom = clip && getComputedStyle(clip).overflowY === "hidden" ? Math.min(window.innerHeight, clip.getBoundingClientRect().bottom) : window.innerHeight;
      const room = bottom - limit.top;
      const messageHeight = Math.round(messages.getBoundingClientRect().height);
      const overflow = Math.max(0, ...fields.map(field => Math.max(field.getBoundingClientRect().right - limit.right, field.getBoundingClientRect().bottom - window.innerHeight)));
      const text = overflow > 1 ? `布局检查失败：输入区域越界 ${Math.round(overflow)} px`
        : messageHeight < room * .55 ? `布局检查失败：对话仅 ${messageHeight} px / 可用 ${Math.round(room)} px`
        : `布局检查通过：对话 ${messageHeight} px / 可用 ${Math.round(room)} px，输入区未越界`;
      setResult(text);
      if (window.parent !== window) window.parent.postMessage({ type: "decky-layout-check", text }, location.origin);
    }, 250);
    return () => clearInterval(timer);
  }, [host]);
  if (!host && window.parent !== window) return null;
  return <output role="status" style={{ position: "fixed", top: 20, left: 20, maxWidth: "calc(100vw - 360px)", color: "white", background: "#25313b", padding: 12 }}>{result}</output>;
}
