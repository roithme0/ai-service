# Chat Details and Loading Feedback

## Status

Evolving concept as of 2026-10-18. Loading-indicator lifetime, automatic detail collapse, post-completion disclosure and manual-toggle scrolling are agreed. The concept is sufficiently detailed to begin implementation in agreed, narrow slices. Remaining interaction and edge-case rules will be resolved before their affected slices.

## Delivery Approach

For each narrow slice, discuss and agree on its details, update this concept as necessary, implement, validate and review before choosing the next slice.

The first agreed slice covers the send icon and detail typography. Register the supplied outline SVG through the existing Angular Material `MatIconRegistry` and render it through the existing `ai-chat:send` control. Use `currentColor` to inherit the themed button color, including its disabled state. Keep the existing accessible button label; the SVG is decorative. Apply primary assistant text styling to intermediate messages and tool names, retaining smaller secondary styling for tool states. Existing technical tool names and the shared tool icon remain in use. Loading and detail disclosure belong to subsequent slices.

The first slice is implemented and code-reviewed. Formatting, lint, 13 tooling tests, 4 application tests and 100 chat UI tests pass. The application suite required a retry with broader process permissions after a worker-start timeout. The send and shared tool icons were reviewed in Edge, including fixes for SVG baseline alignment and clipping. Longer primary-size tool names may wrap more often.

The third agreed slice provides turn association and lifecycle metadata without visual, disclosure or scrolling changes. Each response fragment retains its actual backend turn ID, and each turn references its stable initiating user message ID. Each turn owns its ordered content, including artifacts interleaved with details. The rendering-only `/ui` contract accepts a host-controlled `turns` collection with `id`, `userMessageId`, ordered `content` and `active`, `completed`, `failed` or `unknown` status. Content `turnId` remains optional for rendering-only hosts. Active includes accepted work waiting to start and closing work whose final answer has arrived before completion.

Snapshots expose ordered backend-provided `turns` records with actual turn identity, initiating user message identity and lifecycle status. The turn-owned timeline foundation now places each ordered timeline, including embedded artifact envelopes, directly within its turn in both internal and HTTP snapshots. SSE upserts use the same self-contained items and turn-local positions. The controller maps each backend turn into a UI turn with ordered content and reconciles accepted submissions from user items in those timelines. The backend reuses its authoritative timeline identities, internal admission identity and retained terminal history. Turn records carry precise `pending`, `in_progress`, `closing`, `completed`, `generation_failed` or `conflict` lifecycle; they replace the separate latest-terminal and active-turn snapshot fields. Terminal outcomes outrank received final text, and pending work is distinct from admitted work. Historical completion is never inferred from a final message or proximity. The controller maps pending, in-progress and closing states to UI active, completed to completed, and generation failure or conflict to failed. Unknown remains a client observation outcome. Recovery considers the latest submitted turn, so newly pending work cannot be confused with an older terminal turn. The controller marks only the affected active turn unknown when observation is interrupted. It does not reconstruct turn associations or fabricate an initiating user anchor at admission. If observation fails before its first snapshot, the accepted user message remains in its acknowledged turn with an unknown outcome and the error remains visible. Unknown outcomes retain received details visibly, including when a final answer was received. Disclosure behavior itself belongs to the next slice.

The explicit final-answer prerequisite carries required `is_final` on backend timeline messages through snapshots and SSE to required UI text `isFinal`. Only retained `MessageRecord` values with `kind: final` set it true. User and unspecified assistant messages remain non-final; intermediate content keeps its separate kind. Position and successful completion never identify a final answer. The marker and final content survive a later failure and do not change turn lifecycle or rendering. Future disclosure places its toggle after the explicit final answer and uses the first timeline item as the expansion scroll anchor; this prerequisite slice implements no disclosure or scrolling changes.

## Context

The shared chat UI displays intermediate assistant messages, tool calls, assistant answers and artifacts in ordered, turn-owned content. Assistant loading feedback uses three animated dots. Intermediate messages and tool rows remain visible after completion.

The supplied references in the root `.temp` folder are:

- `chat with loading indicator.html`: three animated dots below the submitted user message while waiting for a response.
- `chat in progress.html`: intermediate assistant text followed by tool rows with completed and running states. No separate dots are rendered in this example.
- `chat with expanded details.html`: intermediate text and tool rows above the completed answer and recipe cards, with a details toggle beneath the answer. The toggle uses a list-tree icon, an expanded state and show/hide labels.
- `3-dots-loading-indicator.svg`: three staggered dots with opacity and vertical movement over a 1.3-second cycle, including a static reduced-motion variant.
- `send.svg`: an outlined horizontal send icon to replace the current send icon.

The HTML examples use Kochwiki content and styling. Their domain content does not establish recipe-specific behavior for the reusable chat library. The supplied SVGs use a fixed foreground color; integration should account for the library's host theme.

## Goal

Allow users to collapse and expand intermediate assistant messages and tool calls, keeping the final answer easy to read while retaining access to the execution details. Rework loading feedback using the supplied three-dot indicator and replace the send icon with the supplied design.

## Proposed Direction

Treat intermediate messages and tool calls as details associated with an assistant turn. Keep final answer text and artifacts available independently of whether those details are expanded. This interpretation follows the completed-answer reference and remains subject to discussion for interleaved content.

### Loading and Execution

The second agreed slice implements the supplied three-dot animation and its lifetime. Show no indicator while submitting the user message. Start the dots immediately after acceptance, together with displaying the user message in history. Preserve the themed foreground color and an accessible loading label. Use the supplied animated SVG as the external template of a reusable Angular component, keeping its animation definitions inside the SVG. Use only the SVG animation for dots, without the loading-text entrance fade. Reduced-motion handling is not required. Conversation startup and errors retain their existing text presentation. Turn grouping, detail disclosure and scrolling changes are outside this slice.

The second slice is implemented. Formatting, lint, 13 tooling tests, 4 application tests and 107 chat UI tests pass. Edge accessibility and DOM checks confirmed the waiting indicator and its absence after visible response content. Animation appearance still needs visual acceptance: transient screenshots did not capture a clear rendered indicator, and subsequent browser capture stalled. The Edge tab remains open for reuse.

The dots bridge the gap from the accepted user message appearing in history to the first response fragment appearing. They are absent while the user message is being sent; no sending text replaces them. Remove them when the first intermediate assistant message or tool call appears. They also disappear if an artifact, final answer or failure is the first visible response content. Dots are shown exclusively when nothing else from that turn can be displayed, excluding the initiating user message. An artifact omitted by the host mapper does not count as visible content. They do not accompany subsequent activity or reappear between steps of the same turn. Previous-turn content does not suppress a new turn's dots.

During execution, show intermediate messages and tool calls as they arrive. There is no action bar or expand/collapse control during the active turn; users cannot collapse or expand details mid-turn.

### Completion and Disclosure

Automatically collapse the turn details when the final assistant message has been generated and the turn has completed. Only then reveal the answer action bar containing the expand/collapse button. Users first encounter that control with the details already collapsed. Final-message arrival alone, before turn completion, does not reveal the action bar.

After completion, interested users can expand the details to understand the agent's actions and collapse them again. Most users are expected to read the final answer without opening the details.

If a turn has no intermediate messages or tool calls, do not show a details button.

### Scrolling

Keep the existing unconditional scroll-to-bottom behavior during execution. Detecting whether users are reading earlier content or allowing them to suspend following live activity is outside scope.

On manual expansion, reveal the details and then scroll the turn's first timeline item to the top of the history viewport, within the available scroll range. This gives users the request context before the expanded details.

On manual collapse, preserve the history's current scroll offset without initiating another scroll. The browser may clamp that offset if the shorter content cannot support it. No viewport-anchor compensation is required.

Keep toggle handling explicit and separate from the existing content/status-driven scrolling. A stable reference to the first timeline item and scrolling after expansion has rendered should be sufficient; exact mechanics belong to implementation.

### Tool Failures

Tool failures can be recoverable steps in otherwise successful turns. They do not force details to remain expanded or require a separate visible warning when details are collapsed. Trust the agent to work around failures where possible and explain essential tool failures or resulting limitations in its final response. Recorded tool outcomes remain available inside the expanded details.

If a turn fails without a final response, keep any received details visible alongside the error. Do not automatically collapse them or introduce a details action bar. If observation is interrupted and the outcome is unknown, keep all received details visible, even if a final answer has already arrived. Do not automatically collapse details or reveal the details action bar.

Use the supplied icon and animation designs as references. Preserve accessible control names, expanded-state semantics, keyboard access when integrating them. Exact styling beyond the requested details, loading and send changes remains to be agreed.

### Detail Typography

Use the primary text style for both intermediate assistant messages and tool-call names. Use the secondary text style only for the tool-call state. This hierarchy follows the visual references and is in scope.

Tool-specific leading icons and user-friendly replacements for technical tool names are out of scope. Keep the existing shared tool icon and technical names.

## Integration Impact

`frontend/projects/chat-ui/ui/lib/components/chat-ui/chat-ui.component.*` renders ordered `ChatTurn` values, each owning its `ChatContent` list. `chat-message.ts` distinguishes intermediate messages, tools, answers, artifacts and failures, with optional turn association and host-controlled per-turn lifecycle metadata.

The backend timeline provides actual turn IDs and stable initiating user identities. The conversation mapper retains that association for messages, details, tool rows, mapped artifacts and failures. The nested snapshot contract exposes each ordered turn with initiating user identity, lifecycle, and timeline, since the latest terminal marker alone cannot establish historical state. The backend owns both association and lifecycle projection; the frontend only maps supplied records and applies live terminal or unknown updates. Closing and terminal stream events derive from the same snapshot as their preceding timeline updates; a final output upsert cannot be skipped by a newer out-of-band terminal lookup. Final-message arrival does not imply completion.

The rendering-only `/ui` entry point must remain usable with host-supplied content, independently of the `/conversation` controller and HTTP transport. Grouping and presentation rules need a clear contract for both consumers.

The component currently scrolls to the bottom after content or status changes. Preserve that behavior during execution and add the agreed manual-toggle behavior without broadening this change into a live-scroll redesign.

The existing demo can exercise the agreed behavior through its real intermediate messages, tool calls, artifacts and failure flow. Recipe rendering is not required to demonstrate this change.

## Scope Boundaries

This concept covers chat detail disclosure, loading feedback, replacement of the send icon and the agreed detail typography. Artifact-card expansion is an existing, separate interaction; its relationship to turn details needs to remain clear.

Token streaming, cancellation, reconnection, persistence and a general chat redesign are not established requirements of this change. Tool-specific icons and friendlier tool labels appear in the references but are explicitly out of scope.

## Open Questions

- Is there one details toggle per turn, positioned beneath its answer as shown?
- How should artifacts that arrive between intermediate messages and tool calls be presented without obscuring their original order?
- What keyboard-focus behavior should accompany collapse when focus is inside the details?
- Should expanded states survive subsequent submissions, component recreation or refresh?
- Is composer styling beyond replacement of the send icon part of this change, or illustrative context?

## Risks

The agreed presentation relies on the agent explaining essential tool failures in its final response; the UI does not independently surface individual tool failures outside collapsed details. Failed turns without a final response retain visible details and an error, and unknown outcomes likewise retain all received details visibly. Unconditional scrolling during execution can interrupt reading earlier content; this existing limitation is explicitly accepted. Collapsing details may clamp the scroll offset when the content becomes shorter. Grouping by proximity alone can associate details with the wrong answer; preserve actual turn association. Reference assets currently live in `.temp`, so eventual implementation must retain required assets in maintained source locations.
