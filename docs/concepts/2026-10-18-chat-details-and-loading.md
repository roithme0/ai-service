# Chat Details and Loading Feedback

## Status

Evolving concept as of 2026-10-18. Loading-indicator lifetime, automatic detail collapse, post-completion disclosure and manual-toggle scrolling are agreed. The concept is sufficiently detailed to begin implementation in agreed, narrow slices. Remaining interaction and edge-case rules will be resolved before their affected slices.

## Delivery Approach

For each narrow slice, discuss and agree on its details, update this concept as necessary, implement, validate and review before choosing the next slice.

The first agreed slice covers the send icon and detail typography. Register the supplied outline SVG through the existing Angular Material `MatIconRegistry` and render it through the existing `ai-chat:send` control. Use `currentColor` to inherit the themed button color, including its disabled state. Keep the existing accessible button label; the SVG is decorative. Apply primary assistant text styling to intermediate messages and tool names, retaining smaller secondary styling for tool states. Existing technical tool names and the shared tool icon remain in use. Loading and detail disclosure belong to subsequent slices.

## Context

The shared chat UI displays intermediate assistant messages, tool calls, assistant answers and artifacts in a flat timeline. Loading feedback is currently a text status after the timeline. Intermediate messages and tool rows remain visible after completion.

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

The dots bridge the gap from sending a user message to the first turn detail appearing. Remove them when the first intermediate assistant message or tool call appears. They do not accompany subsequent tool activity or reappear between steps of the same turn.

During execution, show intermediate messages and tool calls as they arrive. There is no action bar or expand/collapse control during the active turn; users cannot collapse or expand details mid-turn.

### Completion and Disclosure

Automatically collapse the turn details when the final assistant message has been generated and the turn has completed. Only then reveal the answer action bar containing the expand/collapse button. Users first encounter that control with the details already collapsed. Final-message arrival alone, before turn completion, does not reveal the action bar.

After completion, interested users can expand the details to understand the agent's actions and collapse them again. Most users are expected to read the final answer without opening the details.

If a turn has no intermediate messages or tool calls, do not show a details button.

### Scrolling

Keep the existing unconditional scroll-to-bottom behavior during execution. Detecting whether users are reading earlier content or allowing them to suspend following live activity is outside scope.

On manual expansion, reveal the details and then scroll the turn's initiating user message to the top of the history viewport, within the available scroll range. This gives users the request context before the expanded details.

On manual collapse, preserve the history's current scroll offset without initiating another scroll. The browser may clamp that offset if the shorter content cannot support it. No viewport-anchor compensation is required.

Keep toggle handling explicit and separate from the existing content/status-driven scrolling. A stable reference to the initiating user message and scrolling after expansion has rendered should be sufficient; exact mechanics belong to implementation.

### Tool Failures

Tool failures can be recoverable steps in otherwise successful turns. They do not force details to remain expanded or require a separate visible warning when details are collapsed. Trust the agent to work around failures where possible and explain essential tool failures or resulting limitations in its final response. Recorded tool outcomes remain available inside the expanded details.

If a turn fails without a final response, keep any received details visible alongside the error. Do not automatically collapse them or introduce a details action bar. The presentation of interrupted observation, where the turn outcome is unknown, remains open.

Use the supplied icon and animation designs as references. Preserve accessible control names, expanded-state semantics, keyboard access and reduced-motion behavior when integrating them. Exact styling beyond the requested details, loading and send changes remains to be agreed.

### Detail Typography

Use the primary text style for both intermediate assistant messages and tool-call names. Use the secondary text style only for the tool-call state. This hierarchy follows the visual references and is in scope.

Tool-specific leading icons and user-friendly replacements for technical tool names are out of scope. Keep the existing shared tool icon and technical names.

## Integration Impact

`frontend/projects/chat-ui/ui/lib/chat-ui.component.*` currently renders a flat `ChatContent` list. `chat-message.ts` distinguishes intermediate messages, tools, answers, artifacts and failures, but does not expose turn identity or per-turn completion state to the rendering component.

The backend timeline already provides turn IDs. The conversation mapper in `frontend/projects/chat-ui/conversation/src/conversation-controller.ts` currently drops that association when producing UI content. A reliable grouping model needs to retain turn identity and expose enough lifecycle information for the chosen interaction rules. A backend contract change is not yet established as necessary.

The rendering-only `/ui` entry point must remain usable with host-supplied content, independently of the `/conversation` controller and HTTP transport. Grouping and presentation rules need a clear contract for both consumers.

The component currently scrolls to the bottom after content or status changes. Preserve that behavior during execution and add the agreed manual-toggle behavior without broadening this change into a live-scroll redesign.

The existing demo can exercise the agreed behavior through its real intermediate messages, tool calls, artifacts and failure flow. Recipe rendering is not required to demonstrate this change.

## Scope Boundaries

This concept covers chat detail disclosure, loading feedback, replacement of the send icon and the agreed detail typography. Artifact-card expansion is an existing, separate interaction; its relationship to turn details needs to remain clear.

Token streaming, cancellation, reconnection, persistence and a general chat redesign are not established requirements of this change. Tool-specific icons and friendlier tool labels appear in the references but are explicitly out of scope.

## Open Questions

- Is there one details toggle per turn, positioned beneath its answer as shown?
- If a turn produces a final answer without any details, should the dots disappear on answer arrival? What if an artifact arrives before any detail?
- Should interrupted observation with an unknown turn outcome use the same visible-details presentation as a failed turn without a final answer?
- How should artifacts that arrive between intermediate messages and tool calls be presented without obscuring their original order?
- What keyboard-focus behavior should accompany collapse when focus is inside the details?
- Should expanded states survive subsequent submissions, component recreation or refresh?
- Is composer styling beyond replacement of the send icon part of this change, or illustrative context?

## Risks

The agreed presentation relies on the agent explaining essential tool failures in its final response; the UI does not independently surface individual tool failures outside collapsed details. Failed turns without a final response retain visible details and an error, while unknown outcomes still need a presentation decision. Unconditional scrolling during execution can interrupt reading earlier content; this existing limitation is explicitly accepted. Collapsing details may clamp the scroll offset when the content becomes shorter. Grouping by proximity alone can associate details with the wrong answer; preserve actual turn association. Reference assets currently live in `.temp`, so eventual implementation must retain required assets in maintained source locations.
