# Frontend testing

See [Change Validation](change-validation.md) for commands and prerequisites.

## Frontend test guidance


Require an assertion for new or changed behavior that meets any of these triggers.

| Trigger | Behavior to protect |
| --- | --- |
| Persistent writes | Whether to send a write, the record or version targeted, the values sent, and handling of success, rejection, retry, or duplicate submission. |
| Identity and permissions | Whether to disclose data or offer an action based on identity, ownership, or session state. |
| Contract and domain meaning | Validation or translation of external data, or a calculation whose result changes domain meaning, such as distinguishing an absent value from zero. |
| Failure and overlapping work | Failure, retry, cancellation, or out-of-order completion that affects whether a user can finish a workflow or whether displayed state is current. |

Assert the observable success outcome and applicable invalid-input or failure outcomes the change handles. For example, invalid input can prevent a request, while server rejection can preserve the user's entries and allow retry. For a behavior-preserving refactor, run the relevant existing tests and add an assertion only for behavior that meets a trigger and lacks coverage. Behavior that depends on layout or native browser interactions requires a real browser.

Choose the smallest test layer that can observe the expected outcome.

| Expected outcome | Test layer |
| --- | --- |
| A return value or error from a function with explicit inputs and no Angular dependencies | Call the function directly in Vitest. |
| A service result, state transition, or HTTP contract | Use the service's public API, Angular TestBed when dependency injection is needed, and the HTTP testing controller when the request or response matters. |
| Angular templates, forms, or component coordination | Render the component in jsdom and assert through rendered output or public interactions. |
| Layout, scrolling, or other native browser behavior | Use the Chromium component suite. |

Cover an expected outcome under its relevant condition once. Existing tests count if their assertions would fail on regression. Extend partial coverage where needed. Reuse a higher-layer assertion that exercises the real behavior under the same condition and observes the same outcome. Add a higher-layer assertion for a distinct outcome that requires that layer, such as user-visible recovery from a service error.

Place the spec beside the code that owns the behavior. Append `.spec.ts` or `.browser.spec.ts` to the source basename, as in `session-controller.spec.ts` and `chat-ui.component.browser.spec.ts`. For a contract with no single owner, place the spec in the feature directory and name it for the contract. Name suites after the public function, service, component, or contract and cases for the outcome and condition, such as `keeps the form editable when the save is rejected`.

Run the real code for the behavior each test claims to cover. Control external dependencies at their boundary. Use Angular's HTTP testing controller for a request or response contract and a typed service stub when only a particular service outcome matters. Use typed fixture builders for ordinary defaults and set decisive inputs, such as zero, `null`, or a stale response, in the case that depends on them.
