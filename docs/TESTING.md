# Testing and compatibility

## Automated checks

```bash
source .venv/bin/activate
npm run check
python scripts/audit_public.py
```

The suite covers credential redaction, file permissions, path and symlink boundaries, approval decisions, process cancellation, streaming, conversation routing, Codex model switching, device-code login, voice lifecycle and interface rendering in both languages. HTTP/TLS integration tests use temporary localhost ports and need `requirements-dev.txt` installed.

Publication tests check that install archives omit local deployment notes and runtime files, reject symlinks, and retain the public documentation. The privacy checker reports paths, line numbers and rule names without printing matched private data. Run Gitleaks separately to supplement the project-specific checks.

## Real Codex, local model stub

With an official Codex binary installed:

```bash
python scripts/smoke_codex.py
python scripts/smoke_models.py --codex /path/to/codex
python scripts/smoke_permissions.py --codex /path/to/codex
python scripts/smoke_sandbox.py --codex /path/to/codex
```

These checks use isolated temporary workspaces and local model stubs. Model and permission checks keep the same native thread across overrides; the model check compares the displayed identity to the actual inference payload. They do not use user credentials or make paid model calls. The sandbox check writes only controlled test files.

## Device verification

Integration has been exercised on an x86-64 Bazzite device with Decky Loader 3.3.0 and Codex CLI 0.164.0: native protocol startup/resume, model switching, sandbox boundaries, account model discovery and PipeWire recording. Account transcription was checked using synthetic speech; microphone transport was separately tested through a localhost transcription endpoint.

A standalone Python success does not prove the frozen Decky runtime works. `scripts/smoke_installed_auth.py`, `scripts/smoke_microphone.py` and `scripts/smoke_installed_voice.py` can check the installed process. Read each script before running: account checks may open a login flow, microphone checks capture audio, and synthetic transcription checks submit the supplied test audio to the account service.

Decky 3.3 uses a single administrative WebSocket. The helper scripts can temporarily replace the Steam frontend's connection. `scripts/decky_control.py install` requests a Steam webhelper restart after installation to refresh the actual frontend. A version on disk or a successful backend call alone does not verify the sidebar UI.

Controller focus, the Steam keyboard, touch input, multiple SteamOS releases and different Decky versions still require broader device testing. Verify the version displayed in the sidebar title after an update.
