# Backend testing

## Backend test guidance

Cover new or changed behavior in any of these areas.

| Area | Outcomes to verify |
| --- | --- |
| Data integrity | What is persisted, which record or version changes, and what commits or rolls back together. |
| Identity and access | How the caller is identified and what they can read or change. |
| Contracts and domain rules | Accepted inputs, returned or outbound data, error mapping, and domain results such as an absent value versus zero. |
| Failure and overlapping work | State after a dependency failure, partial success, retry, or concurrent operation, including cleanup and retryability. |

Assert success and the rejection or recovery paths the change handles. Check relevant side effects, such as stored state after a rejected write. When testing concurrency, overlap work through independent sessions or requests and check both caller outcomes and final state. For a behavior-preserving refactor, run the relevant tests and add coverage where an outcome above lacks an assertion. Use line coverage as a diagnostic.

### Choose the test layer

Use the smallest layer that exercises the code enforcing the outcome.

| What enforces the outcome | Where to test |
| --- | --- |
| A calculation, schema, or policy | Call the function, schema, or public service method directly. |
| A service or outbound adapter | Exercise its public entry point with controlled dependency responses. Use a test transport to inspect outbound HTTP when the request is part of the contract. |
| HTTP or MCP routing, validation, identity, or error mapping | Exercise the real FastAPI endpoint or MCP tool with an in-process client. |
| Deployed infrastructure, such as gateway forwarding or object-store signatures | Use the existing [deployment checks](../../deployment/tests/). |

Cover each outcome under its relevant condition once. An existing test, including one at a higher layer, counts if it exercises the real behavior, would fail on the same regression, and runs during relevant validation. Add another assertion for a distinct outcome, such as the HTTP status and body for a failure already tested at the service layer.

### Cover HTTP endpoints and MCP tools

- Assert that every guarded entry point rejects an unauthenticated caller. A parameterized test can cover multiple entry points. Cover expired or invalid credentials in shared authentication tests.
- Where ownership is enforced, also exercise access to another owner's resource with an authenticated caller. Assert the expected denial or filtering for a read and verify stored state is unchanged after a rejected write.
- Test new or changed caller-visible behavior at the entry point, including request handling, response shape, and error mapping as applicable. Use schema tests for individual field rules and OpenAPI assertions for declared requirements. Verify runtime enforcement through a request and follow the [API contract update process](general.md#update-generated-contracts) when the shared HTTP contract changes.

### Name tests and set up data

Place `test_<behavior_or_contract>.py` in the owning area under `backend/tests/`. Name cases for the expected outcome and condition. Reuse typed fixtures for defaults and keep inputs that determine the outcome visible in the case. Run the real code responsible for the behavior and control external dependencies at their boundary.

See [Change Validation](change-validation.md) for commands and prerequisites.
