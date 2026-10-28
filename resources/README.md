# Codex model metadata

`codex-models.json` is the unmodified bundled catalog from OpenAI Codex
`rust-v0.164.0`, matching the plugin's pinned native runtime.

- Source: https://github.com/openai/codex/blob/rust-v0.164.0/codex-rs/models-manager/models.json
- Git blob SHA-1: `72a78e0eacf94103f4babda2a5245aba4ce848c1`
- License: Apache-2.0; see the bundled Codex license and notices.

ChatGPT agent turns use this versioned metadata through Codex's
`model_catalog_json` option, avoiding blocking retries when remote model discovery
is unavailable. Authentication, routing requirements, and model requests still
use the official Codex runtime. Explicitly configured external Codex binaries do
not automatically receive this version-specific catalog.
