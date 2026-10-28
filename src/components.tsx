import { useState } from "react";
import { DialogButton, Focusable, TextField } from "@decky/ui";
import { FiArrowUp, FiCheck, FiLoader, FiMic, FiShield, FiSquare, FiTerminal, FiX } from "react-icons/fi";
import { api, isRunning } from "./api";
import type { AgentController } from "./api";
import type { AgentItem, PendingRequest } from "./types";
import { useSpeech } from "./useSpeech";
import { appendTranscript } from "./speech-state";
import { PermissionPicker } from "./Permissions";
import type { PermissionMode } from "./types";
import { connectionModel } from "./settings-state";
import { useI18n } from "./locale";
import { ModelPicker, useModelCatalog } from "./ModelPicker";

export const statusText: Record<string, string> = {
  idle: "就绪", running: "处理中", waiting: "待确认", completed: "已完成", failed: "失败", cancelled: "已停止",
};

export function ErrorNotice({ agent }: { agent: AgentController }) {
  const t = useI18n();
  return agent.error ? <div className="da-error" role="alert"><span>{t(agent.error)}</span>
    <DialogButton className="da-button da-ghost" onClick={() => agent.setError("")}><FiX /><span className="da-sr-only">{t("关闭提示")}</span></DialogButton>
  </div> : null;
}

export function RequestCard({ request, agent }: { request: PendingRequest; agent: AgentController }) {
  const t = useI18n();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const respond = (approved: boolean) => void agent.act(async () => {
    if (agent.selected) await api.respond(agent.selected, request.id, approved, answers);
  });
  return <section className="da-approval"><h3><FiShield />{t(request.title)}</h3>
    {request.detail && <Focusable><pre className="da-code">{request.detail}</pre></Focusable>}
    {request.questions.map(q => <div className="da-question" key={q.id}><p>{q.question}</p>
      <div className="da-options">{q.options?.map(option => <DialogButton key={option.label}
        className={`da-button ${answers[q.id] === option.label ? "da-active" : ""}`}
        onClick={() => setAnswers({ ...answers, [q.id]: option.label })}>{option.label}</DialogButton>)}</div>
      <div className="da-input"><TextField aria-label={q.question} value={answers[q.id] || ""} placeholder={t("输入回答")}
        onChange={e => setAnswers({ ...answers, [q.id]: e.target.value })} /></div>
    </div>)}
    <div className="da-actions">
      {request.kind === "approval" && <DialogButton disabled={agent.working} className="da-button" onClick={() => respond(false)}>{t("拒绝")}</DialogButton>}
      <DialogButton disabled={agent.working || (request.kind === "input" && request.questions.some(q => !answers[q.id]?.trim()))}
        className="da-button da-primary" onClick={() => respond(true)}><FiCheck />{request.kind === "input" ? t("提交") : t("允许一次")}</DialogButton>
    </div>
  </section>;
}

export function Message({ item }: { item: AgentItem }) {
  const t = useI18n();
  const [expanded, setExpanded] = useState(false);
  if (item.role === "tool") return <div className="da-tool"><DialogButton className="da-button da-tool-toggle" onClick={() => setExpanded(!expanded)}>
    <FiTerminal /><span>{t(item.title || "工具")}</span><span className="da-muted">{item.status === "inProgress" ? t("执行中") : item.status === "failed" ? t("失败") : item.status === "interrupted" ? t("已停止") : ""}</span>
    <span className="da-muted">{expanded ? t("收起") : t("详情")}</span></DialogButton>
    {expanded && <Focusable><pre className="da-code">{item.text}</pre></Focusable>}
  </div>;
  return <div className={`da-item da-item-${item.role}`}><div className="da-item-head">{item.role === "user" ? t("你") : item.role === "system" ? t("提示") : "Agent"}</div>
    <Focusable><div className="da-message">{item.text}</div></Focusable></div>;
}

export function ActiveTask({ agent }: { agent: AgentController }) {
  const t = useI18n();
  if (!agent.data?.active_id || agent.data.active_id === agent.selected) return null;
  const active = agent.data.sessions.find(s => s.id === agent.data!.active_id);
  return <div className="da-active-task"><span>{t("任务运行中")}{active ? `：${active.title}` : ""}</span>
    <DialogButton className="da-button da-ghost" onClick={() => agent.setSelected(agent.data!.active_id)}>{t("查看")}</DialogButton></div>;
}

export function Composer({ agent, draft, setDraft }: { agent: AgentController; draft: string; setDraft: (v: string) => void }) {
  const t = useI18n();
  const running = isRunning(agent.session);
  const blocked = !!agent.data?.active_id && agent.data.active_id !== agent.selected;
  const signingIn = agent.data?.auth.busy || ["checking", "starting", "waiting"].includes(agent.data?.auth.phase || "");
  const chatgpt = agent.data?.settings.engine === "codex" && agent.data?.settings.auth_mode === "chatgpt";
  const catalog = useModelCatalog(agent, chatgpt);
  const voice = useSpeech(agent.selected, text => setDraft(appendTranscript(draft, text)), agent.setError);
  const capture = voice.phase === "recording" || voice.phase === "ready";
  const mode = (running ? agent.session?.permission_mode : agent.data?.settings.permission_mode) || "ask";
  const changePermission = (permission_mode: PermissionMode) => void agent.act(async () => {
    await api.save({ permission_mode }); await agent.refresh();
  });
  const changeModel = (chatgpt_model: string) => void agent.act(async () => {
    await api.save({ chatgpt_model }); await agent.refresh();
  });
  const send = async () => { if (await agent.send(draft)) setDraft(""); };
  return <div className="da-composer"><div className="da-compose-row"><div className="da-input">
    <TextField value={draft} disabled={running || blocked || signingIn || agent.working || voice.busy} aria-label={t("任务")} placeholder={blocked ? t("请先完成或停止正在运行的任务") : t("输入任务…")}
      onChange={e => setDraft(e.target.value)} onKeyDown={e => {
        if (e.key === "Enter" && !e.nativeEvent.isComposing && !running && !blocked && !signingIn && !agent.working && !voice.busy) void send();
      }} /></div>
    {!running && <DialogButton className={`da-button ${capture ? "da-primary da-voice-stop" : "da-ghost"}`} disabled={blocked || signingIn || agent.working || !agent.session || ["starting", "transcribing", "cancelling"].includes(voice.phase)}
      onClick={() => { agent.setError(""); void (capture ? voice.finish() : voice.start()); }}>
      {capture ? <FiSquare /> : voice.busy ? <FiLoader /> : <FiMic />}<span className={capture ? undefined : "da-sr-only"}>{capture ? t("结束转写") : t("语音输入")}</span></DialogButton>}
    {voice.busy && <DialogButton className="da-button da-ghost" disabled={voice.phase === "cancelling"} onClick={() => void voice.cancel()}><FiX /><span className="da-sr-only">{t("取消录音或转写")}</span></DialogButton>}
    {running ? <DialogButton disabled={agent.working} className="da-button da-danger" onClick={() => void agent.stop()}><FiSquare />{t("停止")}</DialogButton>
      : !voice.busy && <DialogButton className="da-button da-primary" disabled={!draft.trim() || blocked || signingIn || agent.working || !agent.session || agent.data?.speech.busy} onClick={() => void send()}><FiArrowUp /><span className="da-sr-only">{t("发送")}</span></DialogButton>}
  </div><div className="da-compose-footer">
    {agent.data?.settings.engine === "codex" && <PermissionPicker value={mode} disabled={running || blocked || signingIn || agent.working || voice.busy || agent.data?.speech.busy}
      onChange={changePermission} />}
    {voice.busy ? <span className="da-voice-status" role="status">{voice.phase === "recording" ? t("录音中 · {seconds}/60 秒", { seconds: voice.seconds }) : voice.phase === "ready" ? t("录音已结束，等待转写") : voice.phase === "starting" ? t("打开麦克风…") : voice.phase === "cancelling" ? t("正在取消…") : t("正在转写…")}</span>
      : chatgpt ? <ModelPicker value={agent.data?.settings.chatgpt_model || ""} catalog={catalog}
        resolved={agent.session?.model === agent.data?.settings.chatgpt_model ? agent.session?.resolved_model : undefined}
        disabled={running || blocked || signingIn || agent.working || agent.data?.speech.busy || !agent.data?.auth.signed_in}
        onChange={changeModel} />
      : <span className="da-composer-context" title={agent.session?.workspace || agent.data?.settings.workspace}>{(agent.session?.items.length ? agent.session.model : connectionModel(agent.data?.settings)) || "Codex"} · {t(statusText[agent.session?.status || "idle"])}</span>}
  </div></div>;
}
