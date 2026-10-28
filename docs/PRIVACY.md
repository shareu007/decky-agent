# Privacy and publication

## Data on the device

- Settings and API keys are stored under Decky's plugin settings directory. Credential files use `0600`; private runtime directories use `0700` when created by this plugin.
- Conversations and Codex's independent `CODEX_HOME` live in Decky's plugin runtime directory. Codex owns account credential storage and refresh. The frontend receives account display information and a temporary login code, not access tokens.
- Voice capture uses a temporary WAV. Transcription, cancellation and plugin cleanup remove the recording; unsubmitted audio expires after the configured short retention period.
- The frontend records only its version, timestamp, window relationship and numeric panel dimensions in a local `diagnostics/frontend.json`. This report contains no chat, account, URL, screenshot or audio content. It is not uploaded by the project.
- Processes running as the same Linux user can read that user's local credential files. These files are not a system keychain.

## Data sent to providers

Task prompts and tool context are sent to the selected model provider. In ChatGPT mode, Codex manages first-party account inference; custom API mode uses the configured provider. A separately configured voice API receives its own key, not the ChatGPT account token or an automatically inherited chat key.

Submitting a recording sends it to the selected transcription service. The account adapter obtains a short-lived credential through Codex and sends it only to the fixed first-party transcription URL, with redirects disabled. This compatibility interface can change. Configure an independent transcription API if needed.

The plugin does not add a project analytics service. Provider data handling and retention are governed by the service you choose. Inspect tool commands before approving them; tools can expose files when the selected permissions allow it.

## Public source and release audit

The initial public release is prepared from explicit source and archive manifests. Local deployment notes, machine identifiers, account data, recordings, development environments, generated caches and previous install archives are excluded. Commit authors use a GitHub noreply address.

The release process checks:

1. The exact candidate files and staged Git blobs, including docs, tests and dependency metadata.
2. Personal home paths, non-example emails, private network addresses, credential shapes and private runtime filenames.
3. An independent, redacted Gitleaks scan of source and Git history.
4. Rebuilt ZIP contents, including embedded frontend source and third-party notices. Native Codex is rebuilt from its integrity-verified official package.

Automated scans have limits. Test fixtures deliberately contain fake credentials and reserved example addresses. Review findings rather than hiding whole source or test directories from a scanner. New files outside the public manifest must be explicitly reviewed before publication.

### Initial v0.1.9 publication check

The prepared source contains 104 files; the full install ZIP contains 110 entries and the Lite ZIP contains 65. Project privacy checks passed for the source index and both archives. Gitleaks 8.30.1, verified against its official release SHA256, reported no leaks in the public source or extracted release text. The native runtime was reconstructed from the integrity-verified official Codex package. Public npm deprecation notices containing an upstream maintainer contact were reviewed as dependency metadata; root package author fields still receive the email check.

Validation also passed 110 backend tests, 27 frontend tests, TypeScript checking and the production build. These results describe this publication snapshot and are not a guarantee about future edits or third-party services.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for commands and [SECURITY.md](../SECURITY.md) for private reports.
