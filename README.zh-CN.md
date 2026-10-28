<div align="center">

# Decky Agent

**把 Codex 放进 Steam Deck 侧边栏。**

在 Decky 内对话、查看工具执行、审批操作，处理设备上的项目和任务。

[![Release](https://img.shields.io/github/v/release/shareu007/decky-agent)](https://github.com/shareu007/decky-agent/releases)
[![Checks](https://github.com/shareu007/decky-agent/actions/workflows/check.yml/badge.svg)](https://github.com/shareu007/decky-agent/actions/workflows/check.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](README.md) · **简体中文**

[下载](https://github.com/shareu007/decky-agent/releases) · [快速开始](#快速开始) · [文档](#文档) · [参与贡献](CONTRIBUTING.md)

</div>

## 关于项目

Decky Agent 是 [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) 插件，内嵌官方 Codex 运行时，也支持自定义模型服务。对话、会话记录、连接设置、语音输入和操作审批都保留在快捷侧边栏内。

目前是早期社区版本。后端集成已在 Bazzite、Decky Loader 3.3.0 上验证；手柄焦点、Steam 软键盘以及不同 SteamOS 版本的兼容性仍需更多实机测试。

## 功能

- **ChatGPT 账号登录**：使用 Codex 官方设备码流程，也可配置自己的 API URL、密钥和模型。
- **模型选择**：输入框旁可选择模型；自动模式显示 Codex 解析的实际模型，切换 Codex 模型保留会话。
- **三种权限模式**：请求批准、帮我批准、完全访问；对话中展示审核结果和工具详情。
- **语音转草稿**：最长录制 60 秒，转写后可编辑、确认发送；支持登录账号或独立转写 API。
- **紧凑对话**：流式回复、会话切换和设置都在一个侧栏内。
- **中文 / English**：在设置中选择界面语言。

## 快速开始

### 1. 安装

需要已安装 Decky Loader 的 x86-64 Linux Steam Deck 环境。完整 ZIP 包含 Codex CLI **0.164.0**，设备无需安装 Node.js。语音录音还需要 PipeWire 的 `pw-record` 或 `pw-cat`。

1. 切换到桌面模式。
2. 从 [Releases](https://github.com/shareu007/decky-agent/releases) 下载 `decky-agent-0.1.9-steamdeck.zip`、对应 `.sha256` 文件和 `install-on-deck.sh`。
3. 打开终端，执行：

   ```bash
   cd ~/Downloads
   sha256sum -c decky-agent-0.1.9-steamdeck.zip.sha256
   bash install-on-deck.sh decky-agent-0.1.9-steamdeck.zip
   ```

   安装脚本需要 `sudo`，会备份旧插件并重启 Decky。安装目录不在默认位置时，可设置 `DECKY_HOME`。
4. 回到游戏模式，打开 **Decky → Decky Agent → 设置**。

Lite 包不包含 Codex，可配合已安装的 Codex 二进制，或使用兼容 API 引擎。

### 2. 连接模型

| 方式 | 配置 |
| --- | --- |
| ChatGPT 账号 | 选择 **Codex → ChatGPT 账号 → 登录 ChatGPT**，在官方页面完成设备码授权，然后选择模型或自动模式。 |
| Responses API | 选择 **Codex → 自定义 API**，填写服务根地址、模型 ID 和可选密钥。服务需要支持 Codex 的 Responses 工具协议。 |
| Chat Completions API | 对支持流式 Chat Completions 和工具调用的服务，选择 **兼容 API**。 |

设置工作目录并保存。`127.0.0.1` 表示 Steam Deck 自己；模型服务运行在其他电脑上时，应填写那台电脑的主机名。能读取模型目录并不代表账号或代理有权调用其中每个模型。

### 3. 开始任务

描述需要完成的工作，查看回复，并审批需要额外权限的操作。可用 **Steam + X** 打开软键盘。语音输入需先在 **设置 → 高级设置** 中启用；点击麦克风录音，再点“结束转写”，识别结果填入草稿，由你确认发送。

## 权限与隐私

| 模式 | 行为 |
| --- | --- |
| 请求批准 | 在工作目录沙箱内执行，额外权限由你批准。 |
| 帮我批准 | 使用相同沙箱，额外权限交由 Codex 自动审核，并在对话中展示结果。 |
| 完全访问 | 取消 Codex 文件、网络沙箱和操作审批。 |

插件始终以普通用户运行；这些模式不提供 root，也不处理 sudo 密码。完全访问可影响当前用户能访问的整个设备；兼容 API 的命令执行同样没有 OS 沙箱，每条命令都需要审批。

API 密钥以 `0600` 权限保存在本地。ChatGPT 凭据由 Codex 管理，使用插件专用的 `CODEX_HOME`。聊天与工具上下文发送给所选模型服务；录音发送给所选转写服务，转写或取消后清理临时文件。账号语音使用兼容接口，可能随服务端变化而失效。

启用设备范围操作前，请阅读 [隐私说明](docs/PRIVACY.md)、[权限细节](docs/PERMISSIONS.md) 和 [安全策略](SECURITY.md)。

## 开发

需要 Node.js 22+、Python 3.11+、npm；设备集成测试需要 Linux 目标环境。

```bash
git clone https://github.com/shareu007/decky-agent.git
cd decky-agent
npm ci
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm run check

# 下载并校验固定版本的官方 Linux Codex 运行时
python scripts/bundle_codex.py
python scripts/package.py
```

运行 `npm run preview`，打开 `http://127.0.0.1:5173/` 可预览界面。预览使用模拟后端和控件，不读取项目、不录音、不执行命令；这些适配器不进入生产前端。

发布源码或安装 ZIP 前执行：

```bash
python scripts/audit_public.py
python scripts/audit_public.py --tracked
python scripts/audit_public.py --archive out/decky-agent-0.1.9-steamdeck.zip
# 另行安装 Gitleaks 后，补充独立密钥扫描：
gitleaks git --redact --no-banner .
```

更多验证见 [测试说明](docs/TESTING.md)，发布范围见 [贡献指南](CONTRIBUTING.md)。

## 文档

- [ChatGPT 登录](docs/AUTH.md)
- [权限模式](docs/PERMISSIONS.md)
- [语音输入](docs/VOICE.md)
- [隐私与发布审计](docs/PRIVACY.md)
- [测试与兼容性](docs/TESTING.md)
- [更新记录](CHANGELOG.md)

## 许可证与致谢

项目原创代码采用 [MIT 许可证](LICENSE)。Codex 和前端依赖保留各自许可证，详见 [第三方声明](THIRD_PARTY_NOTICES.md)。发布包包含相关声明和可重新构建的前端源码。

基于 [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) 和 [OpenAI Codex](https://github.com/openai/codex) 构建，属于独立社区项目。
