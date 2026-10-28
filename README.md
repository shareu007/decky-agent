<div align="center">

# Decky Agent

**Codex, in your Steam Deck sidebar.**

Chat with an agent, review its actions, and work on your device without leaving Decky.

[![Release](https://img.shields.io/github/v/release/shareu007/decky-agent)](https://github.com/shareu007/decky-agent/releases)
[![Checks](https://github.com/shareu007/decky-agent/actions/workflows/check.yml/badge.svg)](https://github.com/shareu007/decky-agent/actions/workflows/check.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**English** · [简体中文](README.zh-CN.md)

[Download](https://github.com/shareu007/decky-agent/releases) · [Quick start](#quick-start) · [Documentation](#documentation) · [Contributing](CONTRIBUTING.md)

</div>

## About

Decky Agent is a [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that puts a coding agent in the quick-access sidebar. It embeds the official Codex runtime and also supports custom model providers. Conversations, settings, voice input and approvals all stay in the sidebar.

This is an early community release. Backend integration has been tested on Bazzite with Decky Loader 3.3.0; controller focus, the Steam keyboard and compatibility across SteamOS releases still need broader device testing.

## Features

- **ChatGPT sign-in** — use Codex's official device-code login, or connect your own API URL, key and model.
- **Model selection** — choose a model beside the input box; automatic mode shows the model resolved by Codex. Switch Codex models while keeping the conversation.
- **Three permission modes** — Ask me, Auto review and Full access, with decisions and tool details visible in chat.
- **Voice to draft** — record up to 60 seconds, transcribe, edit and send. Supports the signed-in account or a separate transcription API.
- **Compact chat** — streaming responses, conversation history and settings in one sidebar.
- **中文 / English** — choose the interface language in Settings.

## Quick start

### 1. Install

You need Decky Loader and an x86-64 Linux Steam Deck environment. The full ZIP includes Codex CLI **0.164.0**; Node.js is not required on the device. Voice recording additionally needs PipeWire's `pw-record` or `pw-cat`.

1. Switch to Desktop Mode.
2. Download `decky-agent-0.1.9-steamdeck.zip`, its `.sha256` file and `install-on-deck.sh` from [Releases](https://github.com/shareu007/decky-agent/releases).
3. In a terminal, run:

   ```bash
   cd ~/Downloads
   sha256sum -c decky-agent-0.1.9-steamdeck.zip.sha256
   bash install-on-deck.sh decky-agent-0.1.9-steamdeck.zip
   ```

   The installer requires `sudo`, backs up an existing plugin and restarts Decky. If Decky uses a custom location, set `DECKY_HOME` when running the script.
4. Return to Game Mode and open **Decky → Decky Agent → Settings**.

The Lite ZIP omits Codex. Use it with a separately installed Codex binary or the compatible API engine.

### 2. Connect a model

| Connection | Setup |
| --- | --- |
| ChatGPT account | Select **Codex → ChatGPT account → Sign in to ChatGPT**. Complete the device-code flow on the official page, then choose a model or Automatic. |
| Responses API | Select **Codex → Custom API** and enter your provider's base URL, model ID and optional API key. The provider must support Codex's Responses tool protocol. |
| Chat Completions API | Select **Compatible API** for providers supporting streamed Chat Completions and tool calling. |

Choose a workspace and save. `127.0.0.1` refers to the Deck itself; use your model server's hostname when it runs on another machine. Model catalog entries do not guarantee access for every account or provider.

### 3. Start a task

Describe what you want done, inspect the response, and approve any requested actions. Use **Steam + X** for the keyboard. To dictate, enable **Settings → Advanced → Voice input**, tap the microphone and tap **Transcribe** when finished. The text fills your draft for review.

## Permissions and privacy

| Mode | Behavior |
| --- | --- |
| Ask me | Runs in the workspace sandbox and asks you about extra access. |
| Auto review | Uses the same sandbox; Codex reviews extra permissions and shows its decision. |
| Full access | Removes Codex's file/network sandbox and approval prompts. |

The plugin runs as your regular user. These modes do not grant root or handle sudo passwords. Full access can affect everything your user can access; compatible API shell execution also has no OS sandbox and requires approval for each command.

API keys are stored locally with `0600` permissions. Codex owns ChatGPT credentials in a plugin-specific `CODEX_HOME`. Chat and tool context go to your selected model provider; audio goes to your selected transcription service. Temporary recordings are cleaned up after transcription or cancellation. Account voice transcription uses a compatibility endpoint and may change independently of the plugin.

Read the [privacy notes](docs/PRIVACY.md), [permission details](docs/PERMISSIONS.md) and [security policy](SECURITY.md) before enabling device-wide actions.

## Development

Requirements: Node.js 22+, Python 3.11+, npm and a Linux target for device integration tests.

```bash
git clone https://github.com/shareu007/decky-agent.git
cd decky-agent
npm ci
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm run check

# Download and verify the pinned official Linux Codex runtime
python scripts/bundle_codex.py
python scripts/package.py
```

For UI development, run `npm run preview` and open `http://127.0.0.1:5173/`. The preview uses mock controls and a simulated backend. It does not read projects, record audio or run commands. Preview adapters are excluded from the production frontend.

Before publishing source or an install ZIP:

```bash
python scripts/audit_public.py
python scripts/audit_public.py --tracked
python scripts/audit_public.py --archive out/decky-agent-0.1.9-steamdeck.zip
# Additional credential scan, using a separately installed Gitleaks:
gitleaks git --redact --no-banner .
```

See [testing](docs/TESTING.md) for local-only Codex integration checks and [contributing](CONTRIBUTING.md) for the publication rules.

## Documentation

- [简体中文指南](README.zh-CN.md)
- [ChatGPT sign-in](docs/AUTH.md)
- [Permission modes](docs/PERMISSIONS.md)
- [Voice input](docs/VOICE.md)
- [Privacy and publication audit](docs/PRIVACY.md)
- [Testing and compatibility](docs/TESTING.md)
- [Changelog](CHANGELOG.md)

## License and acknowledgments

Decky Agent's original code is [MIT licensed](LICENSE). Codex and frontend dependencies retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md). Release archives include the relevant notices and rebuildable frontend source.

Built with [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) and [OpenAI Codex](https://github.com/openai/codex). An independent community project.
