import type { ReactNode } from "react";
import type { DialogButtonProps, FocusableProps, TextFieldProps, DropdownItemProps, DropdownProps, ToggleFieldProps } from "@decky/ui";

export function DialogButton({ children, onClick, className, disabled, style }: DialogButtonProps) {
  return <button className={`DialogButton ${className || ""}`} disabled={disabled} style={style} onClick={e => onClick?.(e.nativeEvent)}>{children}</button>;
}
export function Focusable({ children, onActivate: _onActivate, onCancel: _onCancel, ...props }: FocusableProps) {
  return <div tabIndex={0} {...props}>{children}</div>;
}
export function TextField({ value, onChange, onKeyDown, disabled, placeholder, bIsPassword, label, "aria-label": ariaLabel }: TextFieldProps) {
  return <div className="DialogInputLabelGroup">{label && <label>{label}</label>}<div className="DialogInput_Wrapper"><input className="DialogInput" aria-label={ariaLabel || String(label || placeholder || "输入")} type={bIsPassword ? "password" : "text"} value={value} onChange={onChange} onKeyDown={onKeyDown} disabled={disabled} placeholder={placeholder} style={{ outline: "none", padding: "6px 0", fontFamily: "inherit" }} /></div></div>;
}
export function DropdownItem({ label, rgOptions, selectedOption, onChange }: DropdownItemProps) {
  return <label>{label}<select value={selectedOption} onChange={e => onChange?.({ label: e.target.value, data: e.target.value })} style={{ maxWidth: "100%", background: "#19232b", color: "white", padding: 8 }}>
    {rgOptions.filter(o => o.data !== undefined).map(o => <option key={String(o.data)} value={String(o.data)}>{o.label}</option>)}
  </select></label>;
}
export function Dropdown({ rgOptions, selectedOption, onChange, menuLabel }: DropdownProps) {
  return <select aria-label={menuLabel || "会话"} value={selectedOption || ""} onChange={e => onChange?.({ label: e.target.value, data: e.target.value })}
    style={{ maxWidth: "100%", background: "#222b32", color: "#e6ecef", padding: "9px 12px", border: "1px solid #303940", borderRadius: 6, font: "inherit", fontSize: 13 }}>
    {rgOptions.filter(o => o.data !== undefined).map(o => <option key={String(o.data)} value={String(o.data)}>{o.label}</option>)}
  </select>;
}
export function ToggleField({ label, checked, onChange }: ToggleFieldProps) {
  return <label style={{ display: "flex", justifyContent: "space-between", fontSize: 12, gap: 12, margin: "18px 0" }}>{label}<input type="checkbox" checked={checked} onChange={e => onChange?.(e.target.checked)} /></label>;
}
export const staticClasses = { Title: "" };
export function PanelSection({ children }: { children: ReactNode }) { return <section>{children}</section>; }
