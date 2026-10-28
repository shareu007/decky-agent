import { useEffect, useRef, useState } from "react";
import { DialogButton, Dropdown } from "@decky/ui";
import { FiPlus, FiSettings, FiTerminal, FiTrash2 } from "react-icons/fi";
import { api, isRunning } from "./api";
import type { AgentController } from "./api";
import { ActiveTask, Composer, ErrorNotice, Message, RequestCard } from "./components";
import { useI18n } from "./locale";

export function Chat({ agent, openSettings, draft, setDraft }: { agent: AgentController; openSettings: () => void; draft: string; setDraft: (value: string) => void }) {
  const t = useI18n();
  const [deleteRequested, setDeleteRequested] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const scroll = useRef<HTMLDivElement>(null);
  const followOutput = useRef(true);
  const chatgpt = agent.data?.settings.auth_mode === "chatgpt";
  const configured = chatgpt ? !!agent.data?.auth.signed_in : !!agent.data?.settings.model;
  useEffect(() => { if (followOutput.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight; }, [agent.session?.revision]);
  useEffect(() => { setDeleteRequested(false); followOutput.current = true; }, [agent.selected]);
  useEffect(() => {
    if (!isRunning(agent.session) || !agent.session?.started_at) { setElapsed(0); return; }
    const update = () => setElapsed(Math.max(0, Math.floor(Date.now() / 1000 - agent.session!.started_at!)));
    update(); const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [agent.session?.status, agent.session?.started_at]);
  const remove = () => void agent.act(async () => {
    if (!agent.selected) return;
    await api.remove(agent.selected);
    const data = await agent.refresh();
    const id = data.active_id || data.sessions[0]?.id || (await api.create()).id;
    await agent.refresh(); agent.setSelected(id); setDeleteRequested(false);
  });
  return <main className="da-main"><div className="da-toolbar">
    {!deleteRequested && <><div className="da-session-picker"><Dropdown menuLabel={t("会话")} selectedOption={agent.selected}
      rgOptions={agent.data?.sessions.map(s => ({ data: s.id, label: (s.title === "新会话" ? t("新会话") : s.title) + (["running", "waiting"].includes(s.status) ? t(" · 运行中") : "") })) || []}
      onChange={option => agent.setSelected(String(option.data))} /></div>
    <DialogButton className="da-button da-ghost da-icon" disabled={agent.working || agent.data?.speech.busy} onClick={() => void agent.newSession()}><FiPlus /><span className="da-sr-only">{t("新建会话")}</span></DialogButton>
    <DialogButton className="da-button da-ghost da-icon" disabled={isRunning(agent.session) || agent.working || !agent.session || agent.data?.speech.busy} onClick={() => setDeleteRequested(true)}><FiTrash2 /><span className="da-sr-only">{t("删除会话")}</span></DialogButton>
    <DialogButton className="da-button da-ghost da-icon" onClick={openSettings}><FiSettings /><span className="da-sr-only">{t("设置")}</span></DialogButton></>}
    {deleteRequested && <><span className="da-muted">{t("删除当前会话？")}</span><div className="da-spacer" /><DialogButton className="da-button da-danger" disabled={agent.working || agent.data?.speech.busy} onClick={remove}>{t("删除")}</DialogButton><DialogButton className="da-button da-ghost" onClick={() => setDeleteRequested(false)}>{t("取消")}</DialogButton></>}
  </div><ActiveTask agent={agent} />
    <div className="da-scroll" ref={scroll} onScroll={() => { const el = scroll.current; if (el) followOutput.current = el.scrollHeight - el.scrollTop - el.clientHeight < 90; }}>
      {!agent.session ? <div className="da-empty"><p>{t("正在加载会话…")}</p></div> : !agent.session.items.length ? <div className="da-empty">
        <FiTerminal /><h1>{configured ? t("开始一个任务") : chatgpt ? t("登录 ChatGPT") : t("先连接模型")}</h1>
        <p>{configured ? t("描述你想完成的事，Agent 会在工作目录中处理。") : chatgpt ? t("在设置中登录账号，使用 Codex。") : t("登录 ChatGPT，或配置自己的 API。")}</p>
        {configured ? <div className="da-suggestions"><DialogButton className="da-button" onClick={() => setDraft(t("检查当前项目的结构，简要说明主要功能。"))}>{t("了解项目")}</DialogButton>
          <DialogButton className="da-button" onClick={() => setDraft(t("检查当前项目，定位并修复一个明确的问题，然后验证结果。"))}>{t("检查问题")}</DialogButton></div>
          : <DialogButton className="da-button" onClick={openSettings}>{t("连接模型")}</DialogButton>}
      </div> : agent.session.items.map(item => <Message key={item.id} item={item} />)}
      {agent.session?.pending.map(request => <RequestCard key={request.id} request={request} agent={agent} />)}
      {agent.session?.status === "running" && <div className="da-thinking" role="status"><i className="da-status-dot" /><span>{t(agent.session.progress || "正在处理")} · {elapsed} {t("秒")}</span></div>}
    </div><ErrorNotice agent={agent} /><Composer agent={agent} draft={draft} setDraft={setDraft} />
  </main>;
}
