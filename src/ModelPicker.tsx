import { useCallback, useEffect, useRef, useState } from "react";
import { Dropdown } from "@decky/ui";
import { api } from "./api";
import type { AgentController } from "./api";
import type { ModelOption } from "./types";
import { useI18n } from "./locale";
import { modelOptions, REFRESH_MODELS } from "./models-state";

export function useModelCatalog(agent: AgentController, enabled = true) {
  const settings = agent.data?.settings;
  const auth = agent.data?.auth;
  const key = JSON.stringify([settings?.engine, settings?.auth_mode, settings?.base_url,
    auth?.signed_in, auth?.account?.email, auth?.account?.plan]);
  const generation = useRef(0);
  const attempted = useRef("");
  const [models, setModels] = useState<ModelOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    generation.current++; attempted.current = "";
    setModels([]); setError(""); setLoading(false);
    return () => { generation.current++; };
  }, [key]);
  const reload = useCallback(async () => {
    const current = ++generation.current;
    attempted.current = key; setLoading(true); setError("");
    try {
      const list = await api.modelCatalog();
      if (current === generation.current) setModels(list);
    } catch (cause) {
      const message = cause && typeof cause === "object" && "message" in cause ? cause.message : cause;
      if (current === generation.current) setError(typeof message === "string" && message.trim() ? message : "无法读取 ChatGPT 模型列表，请检查登录状态和网络；也可留空使用默认模型");
    } finally {
      if (current === generation.current) setLoading(false);
    }
  }, [key]);
  const idle = !agent.working && !agent.data?.active_id && !agent.data?.speech.busy && !auth?.busy;
  useEffect(() => {
    if (enabled && settings?.auth_mode === "chatgpt" && auth?.signed_in && idle && attempted.current !== key) void reload();
  }, [enabled, settings?.auth_mode, auth?.signed_in, idle, key, reload]);
  return { models, loading, error, reload };
}

export function ModelPicker({ value, resolved, catalog, disabled, onChange }: {
  value: string; resolved?: string; catalog: ReturnType<typeof useModelCatalog>;
  disabled?: boolean; onChange: (model: string) => void;
}) {
  const t = useI18n();
  const options = modelOptions(catalog.models, value, resolved, t);
  options.push({ data: REFRESH_MODELS, label: t(catalog.error ? "重试读取模型" : "刷新模型列表") });
  return <div className="da-model-picker" title={catalog.error ? t(catalog.error) : resolved ? t("上次使用：{model}", { model: resolved }) : t("模型来自 Codex 目录，实际可用性取决于账号权限。") }>
    <Dropdown menuLabel={t("模型")} selectedOption={value} rgOptions={options} disabled={disabled || catalog.loading}
      onChange={option => { const model = String(option.data); if (model === REFRESH_MODELS) void catalog.reload(); else onChange(model); }} />
    {catalog.loading && <span className="da-sr-only" role="status">{t("读取模型…")}</span>}
    {catalog.error && <span className="da-sr-only" role="alert">{t(catalog.error)}</span>}
  </div>;
}
