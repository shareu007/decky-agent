import { Dropdown } from "@decky/ui";
import type { PermissionMode } from "./types";
import { useI18n } from "./locale";

export const permissionOptions: { data: PermissionMode; label: string }[] = [
  { data: "ask", label: "请求批准" },
  { data: "auto", label: "帮我批准" },
  { data: "full", label: "完全访问" },
];

export const permissionHelp: Record<PermissionMode, string> = {
  ask: "在工作目录沙箱内执行；需要额外文件或网络权限时，由你批准。",
  auto: "在工作目录沙箱内执行；需要额外权限时，由 Codex 官方自动审核，结果显示在对话中。",
  full: "取消 Codex 文件和网络沙箱，不再请求 Codex 操作审批。仍以普通用户运行，需要 sudo 的安装操作仍需系统授权。",
};

export function PermissionPicker({ value, disabled, onChange }: {
  value: PermissionMode; disabled?: boolean; onChange: (value: PermissionMode) => void;
}) {
  const t = useI18n();
  return <div className={`da-permission-picker ${value === "full" ? "da-permission-full" : ""}`} title={t(permissionHelp[value])}>
    <Dropdown menuLabel={t("权限模式")} disabled={disabled} selectedOption={value} rgOptions={permissionOptions.map(option => ({ ...option, label: t(option.label) }))}
      onChange={option => onChange(option.data as PermissionMode)} />
  </div>;
}
