# Third-party software

Decky Agent's own code is MIT licensed. It is an independent project, not an
official OpenAI or Decky product.

- **Codex CLI 0.164.0**, Copyright OpenAI: Apache License 2.0. Official source:
  https://github.com/openai/codex, official package: `@openai/codex@0.164.0-linux-x64`.
  The native runtime is redistributed unmodified in `bin/codex-runtime/`.
  Matching upstream model metadata is retained in `resources/codex-models.json`;
  its exact source and Git blob hash are recorded in `resources/README.md`.
  The package SHA-512 and source URL are recorded in `bin/CODEX_RUNTIME.json`.
  The upstream runtime's voice NOTICE, manifests, sources, and dependency licenses
  are retained under `bin/codex-runtime/codex-resources/voice/`.
  The Apache 2.0 license is included as `licenses/CODEX-APACHE-2.0.txt`.
- **@decky/api 1.1.3**, SteamDeckHomebrew: LGPL-2.1. Its original license,
  TypeScript source, and distributable modules are retained in `licenses/decky-api/`.
  The application's frontend source and build configuration are included in
  `source/`. To rebuild with a modified library, run `npm ci` in `source/`, replace
  `source/node_modules/@decky/api/` with your modified library, then run
  `npm run build`. Reverse engineering for debugging library modifications is
  not restricted by this project.
- **@decky/rollup**, SteamDeckHomebrew: BSD-3-Clause (build tooling).
  **@decky/ui** is provided by Decky Loader at runtime, not bundled in the frontend.
- **react-icons**, Copyright React Icons contributors: MIT.
  Feather icons, Copyright Cole Bemis: MIT.
- React is provided by Steam at runtime; browser-preview React is a development
  dependency and is not included in the Decky frontend bundle.

Frontend dependency license texts are included in `licenses/FRONTEND.txt`.
