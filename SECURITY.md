# Security policy

The current 0.1.x line receives fixes as development continues. This is an early release; review requested commands and use a dedicated workspace.

## Reporting a vulnerability

Use [private vulnerability reporting](https://github.com/shareu007/decky-agent/security/advisories/new) in this repository's Security tab. Include the version, a minimal reproduction and the affected boundary. Remove API keys, access tokens, device codes, account details, private paths, chat history and recordings from attachments. Avoid public issues for credential leaks or exploitable vulnerabilities.

## Boundaries

- The plugin runs as a regular Linux user and does not grant sudo access.
- Ask me and Auto review use the Codex workspace sandbox. Full access removes the Codex file/network sandbox and approval prompts.
- Compatible API shell execution is not OS-sandboxed and needs per-command approval.
- Model providers receive task context and tool results. Voice providers receive the recording you submit for transcription.
- Local credential files are readable by processes running as the same user. The plugin does not provide a system keychain.
- Account voice transcription follows a Codex compatibility endpoint; an upstream change can require a plugin update or a separate transcription API.

See [privacy](docs/PRIVACY.md) and [permissions](docs/PERMISSIONS.md) for storage and execution details.
