import { useEffect, useState } from "react";
import { DialogButton, DropdownItem, TextField, ToggleField } from "@decky/ui";
import { FiChevronDown, FiChevronUp } from "react-icons/fi";
import { api } from "./api";
import type { AgentController } from "./api";
import type { Settings } from "./types";
import { ErrorNotice } from "./components";
import { configurationSessionAction } from "./settings-state";
import { PermissionPicker, permissionHelp } from "./Permissions";
import { translator } from "./i18n";
import { LocaleProvider } from "./locale";
import { ModelPicker, useModelCatalog } from "./ModelPicker";

export function ConnectionSettings({ agent, onSaved }: { agent: AgentController; onSaved: () => void }) {
  const [form, setForm] = useState<Settings>(agent.data!.settings);
  const t = translator(form.language);
  const [key, setKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [speechKey, setSpeechKey] = useState("");
  const [clearSpeechKey, setClearSpeechKey] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const auth = agent.data!.auth;
  const accountMode = form.engine === "codex" && form.auth_mode === "chatgpt";
  const catalog = useModelCatalog(agent, accountMode && form.auth_mode === agent.data?.settings.auth_mode);
  const signingIn = auth.busy || ["checking", "starting", "waiting"].includes(auth.phase);
  const operationBlocked = agent.working || !!agent.data?.active_id || !!agent.data?.speech.busy || !agent.session;
  const disabled = operationBlocked || signingIn;
  useEffect(() => {
    if (accountMode && agent.data?.settings.auth_mode !== "chatgpt" && auth.phase === "unknown") void agent.act(async () => { await api.account(); await agent.refresh(); });
  }, [accountMode, auth.phase, agent.data?.settings.auth_mode]);
  useEffect(() => { setModels([]); }, [auth.signed_in, auth.account?.email]);
  const update = <K extends keyof Settings>(name: K, value: Settings[K]) => { setForm({ ...form, [name]: value }); setNotice(""); };
  const persist = async () => {
    const saved = await api.save({ ...form, api_key: key, clear_api_key: clearKey,
      speech_api_key: speechKey, clear_speech_api_key: clearSpeechKey });
    setSpeechKey(""); setClearSpeechKey(false);
    setForm(saved); setKey(""); setClearKey(false); setNotice(t("设置已保存"));
    await agent.refresh();
    const action = configurationSessionAction(agent.session, saved, agent.data!.sessions.length);
    if (action === "capacity") {
      setNotice(t("设置已保存。请返回对话，删除一个旧会话后新建会话以使用新配置。"));
      return false;
    }
    if (action === "create") {
      const created = await api.create();
      await agent.refresh(); agent.setSelected(created.id);
    }
    return action;
  };
  const save = (readModels = false) => void agent.act(async () => {
    if (!await persist()) return;
    if (readModels) {
      if (accountMode) { await catalog.reload(); await agent.refresh(); return; }
      const list = await api.models(); setModels(list);
      setNotice(list.length ? t("已读取 {count} 个模型。", { count: list.length }) : t("服务没有提供模型列表，可手动填写。"));
      await agent.refresh();
    } else onSaved();
  });
  const login = () => void agent.act(async () => {
    const action = await persist();
    if (!action) return;
    if (action === "reuse" && agent.session?.items.length) {
      const created = await api.create();
      await agent.refresh(); agent.setSelected(created.id);
    }
    await api.login(); await agent.refresh();
  });
  const accountAction = (operation: () => Promise<unknown>) => void agent.act(async () => { await operation(); await agent.refresh(); });
  const field = (name: "base_url" | "model" | "chatgpt_model" | "workspace" | "codex_path" | "instructions" | "speech_base_url" | "speech_model", label: string, placeholder?: string) => <div className="da-field"><label>{label}</label>
    <div className="da-input"><TextField aria-label={label} disabled={disabled} value={form[name]} placeholder={placeholder} onChange={e => update(name, e.target.value)} /></div></div>;
  return <LocaleProvider language={form.language}><main className="da-settings"><div className="da-settings-inner">
    <div className="da-field"><DropdownItem label={`${t("界面语言")} / Language`} disabled={disabled}
      rgOptions={[{ data: "zh-CN", label: "中文" }, { data: "en", label: "English" }]} selectedOption={form.language || "zh-CN"}
      onChange={option => update("language", option.data === "en" ? "en" : "zh-CN")} />
      <p className="da-hint">{t("只改变界面语言，保留聊天内容和自定义指令。")}</p></div>
    <div className="da-field"><label>{t("引擎")}</label><div className="da-engine-picker">
      <DialogButton disabled={disabled} className={`da-button ${form.engine === "codex" ? "da-active" : ""}`} onClick={() => update("engine", "codex")}>Codex</DialogButton>
      <DialogButton disabled={disabled} className={`da-button ${form.engine === "compatible" ? "da-active" : ""}`} onClick={() => { setForm({ ...form, engine: "compatible", auth_mode: "api" }); setModels([]); }}>{t("兼容 API")}</DialogButton>
    </div><p className="da-hint">{accountMode ? t("使用官方 Codex 和 ChatGPT 账号。") : form.engine === "codex" ? t("需要支持 Responses API 的模型服务。") : t("需要支持 Chat Completions 和工具调用的服务。")}</p></div>
    {form.engine === "codex" && <div className="da-field"><label>{t("连接方式")}</label><div className="da-engine-picker">
      <DialogButton disabled={disabled} className={`da-button ${accountMode ? "da-active" : ""}`} onClick={() => { update("auth_mode", "chatgpt"); setModels([]); }}>{t("ChatGPT 账号")}</DialogButton>
      <DialogButton disabled={disabled} className={`da-button ${!accountMode ? "da-active" : ""}`} onClick={() => { update("auth_mode", "api"); setModels([]); }}>{t("自定义 API")}</DialogButton>
    </div></div>}
    {accountMode ? <section className="da-account">
      {auth.login ? <><p className="da-hint">{t("用手机或电脑打开官方地址，登录并输入授权码：")}</p>
        <p className="da-auth-url">{auth.login.url}</p><div className="da-auth-code" aria-label={t("设备授权码")}>{auth.login.code}</div>
        <p className="da-hint" role="status">{t("等待授权，完成后会自动更新。关闭侧栏后登录仍可继续；重载插件会取消。")}</p>
        <DialogButton disabled={operationBlocked} className="da-button" onClick={() => accountAction(() => api.cancelLogin(auth.login!.id))}>{t("取消登录")}</DialogButton>
      </> : auth.signed_in ? <><div className="da-account-name">{auth.account?.email || t("已登录 ChatGPT")}</div>
        {auth.account?.plan && <p className="da-hint">{auth.account.plan} · {t("按账号可用的 Codex 权益使用")}</p>}
        <div className="da-actions"><DialogButton disabled={disabled} className="da-button da-ghost" onClick={() => accountAction(api.account)}>{t("刷新状态")}</DialogButton>
          <DialogButton disabled={disabled} className="da-button da-ghost" onClick={() => accountAction(api.logout)}>{t("退出登录")}</DialogButton></div>
      </> : <><p className="da-hint">{t("登录 ChatGPT 使用 Codex，无需填写 API Key。")}</p>
        <DialogButton disabled={disabled || !agent.data?.codex_available} className="da-button da-primary" onClick={login}>{signingIn ? t("正在连接…") : t("登录 ChatGPT")}</DialogButton>
        <p className="da-hint">{t("若设备码登录未启用，请先在 ChatGPT 安全设置中启用。")}</p>
      </>}
      {auth.error && <p className="da-hint" role="alert">{t(auth.error)}</p>}
    </section> : <>{field("base_url", t("API 地址"), "https://api.openai.com/v1")}
    <div className="da-field"><label>API Key <span className="da-muted">{clearKey ? t("保存时清除") : form.api_key_set ? t("已保存") : t("可留空")}</span></label><div className="da-key-row">
      <div className="da-input"><TextField aria-label="API Key" bIsPassword disabled={disabled} value={key} placeholder={form.api_key_set ? t("留空保留现有密钥") : t("输入密钥；免鉴权服务可留空")}
        onChange={e => { setKey(e.target.value); setClearKey(false); }} /></div>
      {form.api_key_set && <DialogButton disabled={disabled} className="da-button da-ghost" onClick={() => setClearKey(!clearKey)}>{clearKey ? t("撤销") : t("清除")}</DialogButton>}
    </div></div></>}
    {accountMode ? <div className="da-field"><label>{t("模型")}</label>
      <ModelPicker value={form.chatgpt_model} catalog={catalog} disabled={disabled || !auth.signed_in || form.auth_mode !== agent.data?.settings.auth_mode}
        onChange={model => update("chatgpt_model", model)} />
      <p className="da-hint">{t("模型来自 Codex 目录，实际可用性取决于账号权限。")}</p>
    </div> : field("model", t("模型"), t("填写模型 ID"))}
    {(!accountMode || form.auth_mode !== agent.data?.settings.auth_mode) && <DialogButton className="da-button da-ghost da-read-models" disabled={disabled || (accountMode && !auth.signed_in)} onClick={() => save(true)}>{t("保存并读取模型列表")}</DialogButton>}
    {!accountMode && !!models.length && <DropdownItem label={t("可用模型")} disabled={disabled} rgOptions={models.map(m => ({ data: m, label: m }))} selectedOption={form.model} onChange={o => update("model", String(o.data))} />}
    {field("workspace", t("工作目录"), "/home/deck/decky-agent-workspace")}
    {form.engine === "codex" && <div className="da-field"><label>{t("权限模式")}</label>
      <PermissionPicker value={form.permission_mode || "ask"} disabled={disabled} onChange={value => update("permission_mode", value)} />
      <p className="da-hint">{t(permissionHelp[form.permission_mode || "ask"])}</p>
    </div>}
    <DialogButton className="da-button da-ghost da-advanced-toggle" onClick={() => setAdvanced(!advanced)}>{advanced ? <FiChevronUp /> : <FiChevronDown />}{t("高级设置")}</DialogButton>
    {advanced && <section className="da-advanced">
      <ToggleField disabled={disabled} label={t("语音输入")} checked={form.speech_enabled} onChange={v => update("speech_enabled", v)} />
      {form.speech_enabled && <div className="da-speech-settings">
        {!(accountMode && !form.speech_base_url.trim()) && field("speech_model", t("转写模型"), t("gpt-transcribe 或服务提供的模型 ID"))}
        {field("speech_base_url", accountMode ? t("独立语音 API（留空使用 ChatGPT 账号）") : t("语音 API 地址（留空复用当前连接）"), t("支持 /audio/transcriptions 的 API 根地址"))}
        {form.speech_base_url.trim() && <div className="da-field"><label>{t("语音 API Key")}<span className="da-muted">{clearSpeechKey ? t("保存时清除") : form.speech_api_key_set ? t("已保存") : t("可留空")}</span></label><div className="da-key-row">
          <div className="da-input"><TextField aria-label={t("语音 API Key")} disabled={disabled} bIsPassword value={speechKey} placeholder={t("单独填写；不会自动使用聊天密钥")}
            onChange={e => { setSpeechKey(e.target.value); setClearSpeechKey(false); }} /></div>
          {form.speech_api_key_set && <DialogButton disabled={disabled} className="da-button da-ghost" onClick={() => setClearSpeechKey(!clearSpeechKey)}>{clearSpeechKey ? t("撤销") : t("清除")}</DialogButton>}
        </div></div>}
        <p className="da-hint">{t("录音最长 60 秒，发送至该转写服务后删除临时音频。文字填入输入框，由你确认发送。")}</p>
        {accountMode && !form.speech_base_url.trim() && <p className="da-hint">{t("使用已登录的 ChatGPT 进行语音转写，无需额外 API Key。")}</p>}
        {!agent.data?.speech.available && <p className="da-hint">{t("尚未检测到 PipeWire 录音工具；需要在 Steam Deck 上检查音频环境。")}</p>}
      </div>}
      {field("instructions", t("自定义指令"))}
      {form.engine === "codex" ? <>{field("codex_path", t("Codex 路径（留空自动查找）"))}
        <p className="da-hint">{agent.data?.codex_available ? t("已检测到 Codex") : t("尚未检测到 Codex，请安装完整运行时或填写路径。")}</p>
        <ToggleField disabled={disabled || form.permission_mode === "full"} label={t("允许命令联网")} checked={form.permission_mode === "full" || form.network_access} onChange={v => update("network_access", v)} />
      </> : <><ToggleField disabled={disabled} label={t("启用命令执行")} checked={form.allow_shell} onChange={v => update("allow_shell", v)} />
        <p className="da-hint">{t("命令需逐次确认，可访问当前用户的其他文件和网络。")}</p>
        <div className="da-field"><label>{t("最大工具轮数")}</label><div className="da-input"><TextField disabled={disabled} aria-label={t("最大工具轮数")} value={String(form.max_steps)} onChange={e => { const n = Number(e.target.value); if (Number.isInteger(n)) update("max_steps", n); }} /></div><p className="da-hint">1–50</p></div>
      </>}
    </section>}
    <ErrorNotice agent={agent} />{notice && <p className="da-hint" role="status">{notice}</p>}
    <div className="da-settings-actions"><DialogButton className="da-button da-primary" disabled={disabled} onClick={() => save()}>{t("保存")}</DialogButton>
      {!!agent.data?.active_id && <span className="da-hint">{t("请先停止当前任务")}</span>}
      {agent.data?.speech.busy && <span className="da-hint">{t("请先结束语音输入")}</span>}
    </div>
  </div></main></LocaleProvider>;
}
