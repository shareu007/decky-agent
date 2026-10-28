import { createRoot } from "react-dom/client";
import { AgentPanel } from "../App";
import { LayoutCheck } from "./LayoutCheck";
import { seedChat } from "./api";

const params = new URLSearchParams(location.search);
const layoutTest = params.has("layout-test");
if (layoutTest) seedChat(params.get("language") === "en" ? "en" : "zh-CN", params.has("chatgpt"));
const scale = Number(params.get("scale")) || 1;
const framed = new URLSearchParams(params);
framed.set("frame", "");
createRoot(document.getElementById("root")!).render(layoutTest && !params.has("frame") ? <>
  <iframe title="Steam Deck 侧栏预览" src={`/?${framed}`}
    style={{ width: 320 * scale, height: Number(params.get("height")) || 480, border: 0, display: "block", marginLeft: "auto" }} />
  <LayoutCheck host />
</> : <><aside style={{ width: 320, maxWidth: "100vw", paddingTop: 30, marginLeft: "auto", background: "#14191e", minHeight: "100vh", transform: scale === 1 ? undefined : `scale(${scale})`, transformOrigin: "top right" }}>
  <style>{`button.DialogButton{box-sizing:content-box;width:100%;display:block;margin:2px 0}.DialogInputLabelGroup{margin-bottom:22px;display:block}.DialogInput_Wrapper{display:flex;flex-direction:row;position:relative;align-items:center}.DialogInput_Wrapper>input.DialogInput{flex:1}`}</style>
  <div style={{ padding: "0 12px 12px", color: "#e6ecef", font: "bold 16px Arial" }}>Decky Agent</div>
  <div className="preview-content" style={params.has("clip") ? { height: Number(params.get("clip")), overflow: "hidden" } : undefined}><AgentPanel /></div>
</aside>{layoutTest && <LayoutCheck />}</>);
