# Frontend validation

From `frontend`, using the locked npm installation:

```powershell
npm.cmd run format:changed
npm.cmd run lint
npm.cmd run test:tooling
npm.cmd run test:app
npm.cmd run test:chat-ui
```

`format:changed` formats whole staged, unstaged, and untracked frontend files with the existing Prettier settings, without staging changes. Review the worktree first: unrelated edits in a changed file are included. Generated conversation contracts, lockfiles, dependencies, caches, build output, and coverage are excluded. Formatting is not a repository-wide migration.

`lint` checks the application, chat UI library, tests, handwritten JavaScript and TypeScript tooling, and external and inline Angular templates. The configuration combines ESLint recommended, TypeScript recommended type-checked, Angular recommended, and template accessibility rules. Errors and warnings both fail validation. Generated conversation contracts are excluded; their existing drift check remains separate. `ng lint ai-service-frontend` and `ng lint chat-ui` each expose the same whole-workspace lint scope. `lint:fix` is an explicit opt-in command; review its diff.

## Codex hooks

Review and trust `.codex/hooks.json` in Codex before relying on the hooks. Its PowerShell commands target `C:/Code/ai-service`; update those paths if the checkout moves. The scripts require Node.js 24, installed frontend dependencies, Git, and Windows PowerShell.

`UserPromptSubmit` records a content fingerprint. `Stop` skips unchanged discussion turns; otherwise it formats changed files, lints the whole frontend, runs tooling regression tests, then runs the application and library Angular test suites in non-watch mode. Lint or test failures stop subsequent checks. Successful results are cached only after all checks pass and a final fingerprint confirms files did not change during validation. The fingerprint includes source, generated contracts, configuration, scripts, the lockfile, installed dependency lock, hook definitions, and Node version.

State and diagnostics live in ignored `frontend/.codex-validation/<session-hash>/`: `state.json`, `lint.log`, `tooling-tests.log`, `tests-ai-service-frontend.log`, and `tests-chat-ui.log`. Lint and tooling tests each have a two-minute timeout; each Angular suite has five minutes, within the fifteen-minute hook timeout. Timeouts fail validation. Without a prompt snapshot, a dirty frontend triggers fallback validation.

Failures or formatter edits request one continuation for correction and diff review. A continued stop reports persistent problems without requesting another continuation. Failed checks are never cached as successes. Missing dependencies or existing lint/test debt must be reported as incomplete validation; broad cleanup needs separate authorization. Hook state tracks the shared worktree, not individual file ownership.

CI runs read-only `npm run lint` in the existing contract-check job before downstream builds. It does not format files or apply lint fixes. Existing build, contract, and package checks remain separate.

## Initial verification ? 2026-10-17

The setup passes all 13 tooling regression tests, 4 application tests, and 100 chat UI library tests. The PowerShell wrapper was checked for unchanged-turn skipping, initial failure feedback, and bounded continuation. Angular test workers timed out in the restricted execution environment; both suites passed when rerun with broader process permissions. Live Codex hook trust/activation still needs verification in the client.

Whole-frontend lint reports 120 errors and zero warnings across six existing files: `conversation-api.spec.ts`, `conversation-controller.spec.ts`, `chat-ui.component.spec.ts`, `app.component.spec.ts`, `demo-transport.spec.ts`, and `tests/composer-autosize.firefox.mts`. No findings are in the newly added tooling. Existing source and tests were left unchanged. The hook stops at lint and CI blocks downstream builds until this debt is resolved; the passing Angular suites were run separately.

The additional strict TypeScript check (`node node_modules/typescript/bin/tsc -p tsconfig.eslint.json --noEmit`) reports two existing issues in the Firefox check: `Promise.withResolvers` needs a newer library declaration than the inherited ES2022 target, and `process.env.FIREFOX_BIN` must use index access. Lint uses the dedicated TypeScript project but does not replace a compiler check.

Reproduce the lint report without modifying source:

```powershell
npm.cmd run lint -- --format json --output-file .angular/cache/lint-report.json
```
