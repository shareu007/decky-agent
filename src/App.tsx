import { useEffect, useRef, useState } from "react";
import { DialogButton, Focusable } from "@decky/ui";
import { FiArrowLeft } from "react-icons/fi";
import { api, useAgent } from "./api";
import { Chat } from "./Chat";
import { ConnectionSettings } from "./Settings";
import { styles } from "./styles";
import { useFrontendReport } from "./useFrontendReport";
import { translator } from "./i18n";
import { LocaleProvider } from "./locale";

export function AgentPanel() {
  const agent = useAgent();
  const t = translator(agent.data?.settings.language);
  const panel = useRef<HTMLDivElement>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [draft, setDraft] = useState("");
  useFrontendReport(panel, !!agent.data && !!agent.session && !settingsOpen);
  useEffect(() => { setDraft(""); }, [agent.selected]);
  const needsAccount = agent.data?.settings.auth_mode === "chatgpt" && agent.data.auth.phase === "unknown" && !agent.working && !agent.data.active_id;
  useEffect(() => {
    if (needsAccount) void agent.act(async () => { await api.account(); await agent.refresh(); });
  }, [needsAccount]);
  return <LocaleProvider language={agent.data?.settings.language}><div ref={panel} className="da-panel"><style>{styles}</style><Focusable className="da-panel-content" onCancel={settingsOpen ? event => { event.stopPropagation(); setSettingsOpen(false); } : undefined}>
    {settingsOpen && <header className="da-panel-head"><DialogButton className="da-button da-ghost" onClick={() => setSettingsOpen(false)}><FiArrowLeft />{t("返回对话")}</DialogButton><div className="da-spacer" /><span className="da-muted">{t("设置")}</span></header>}
    {!agent.data ? <div className="da-loading">{agent.error || t("正在连接…")}</div> : settingsOpen
      ? <ConnectionSettings agent={agent} onSaved={() => setSettingsOpen(false)} /> : <Chat agent={agent} openSettings={() => setSettingsOpen(true)} draft={draft} setDraft={setDraft} />}
  </Focusable></div></LocaleProvider>;
}
