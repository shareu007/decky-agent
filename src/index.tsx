import { definePlugin } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { FiTerminal } from "react-icons/fi";
import { AgentPanel } from "./App";
import { FRONTEND_VERSION } from "./version";

export default definePlugin(() => {
  return {
    name: "Decky Agent",
    titleView: <div className={staticClasses.Title}>Decky Agent <span style={{ fontSize: 10, opacity: .6 }}>v{FRONTEND_VERSION}</span></div>,
    content: <AgentPanel />,
    icon: <FiTerminal />,
  };
});
