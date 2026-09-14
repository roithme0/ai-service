# AI-assisted Recipe Improvement

## Status

Draft. Defines the AI Service backend and reusable chat UI for bounded recipe improvement. The wider product flow and Kochwiki responsibilities remain documented in the neighboring planning repository.

## Context

The AI Service should provide a focused chat capability that improves one complete recipe through a short-lived conversational session. The caller supplies the source recipe and all foodstuffs currently available for proposals. The service uses generic recipe-improvement instructions and returns structured recipe proposals.

This concept covers AI orchestration, proposal production, short-lived conversation state, and a reusable chat UI that can be embedded into Kochwiki. Kochwiki remains responsible for recipe data, foodstuff data, authorization, domain-specific proposal presentation, validation at its boundary, and persistence through its own draft lifecycle.

## Decision

Introduce recipe improvement as a bounded, stateful AI Service capability rather than as unrestricted general chat.

Each session:

- is initialized with one complete source-recipe snapshot and its opaque external reference;
- receives a snapshot of the foodstuffs available for use in proposals;
- uses generic instructions to discuss recipe changes in light of the user's stated goals and constraints;
- supports clarification, questions, and iterative proposal refinement;
- retains its conversation, proposals, and proposal lineage in short-lived AI Service state; and
- expires without becoming durable recipe or chat storage.

The service produces immutable, complete recipe proposals. It assigns proposal identifiers, ordering, timestamps, and base references deterministically. The model supplies conversational content and structured recipe candidates but does not invent lifecycle metadata.

The AI Service also owns generic chat UI behavior. The UI presents conversational content and proposal placement but delegates proposal rendering to a renderer supplied by the host application.

## Foodstuff Boundary

The initial capability may use only foodstuffs included in the caller-provided availability snapshot. A proposal ingredient references an available foodstuff by its opaque external identifier. The proposal validator rejects unknown references before emitting an artifact.

Providing the availability snapshot up front is intentionally the first integration. It keeps foodstuff discovery deterministic and avoids granting the model a domain lookup capability. This is appropriate while the Kochwiki catalogue remains small enough to fit within an explicitly configured context budget.

Later iterations may replace or supplement the snapshot with a bounded foodstuff search or lookup tool. Proposing a foodstuff that does not yet exist, creating foodstuffs, and resolving free-text ingredients into new catalogue entries are out of scope.

The snapshot represents allowed references, not AI Service-owned domain data. It should contain only the fields needed to choose and explain an ingredient. The exact schema and catalogue-size limit remain contract-design questions.

## Recipe-Improvement Instructions

The initial capability uses generic instructions to help users explore practical recipe changes aligned with their stated goals, preferences, and constraints. It should explain relevant tradeoffs and uncertainty without presenting unvalidated optimization criteria as established.

Health-related questions receive cautious recipe-level suggestions, not diagnosis, treatment, or promised health outcomes. Specific dietary or medical optimization criteria are not part of this initial capability.

The model may discuss different user-supplied goals, but the service does not claim to evaluate proposals against a defined nutrition or medical standard.

## Proposal Behavior

- A proposal contains the complete recipe content needed by the caller, not a patch.
- Every ingredient must reference the session's availability snapshot.
- A proposal identifies the source recipe or an earlier session proposal as its base.
- One assistant turn may emit multiple proposals when alternatives are requested.
- The assistant can explain proposals in its conversational response; explanations are not required fields on individual proposal artifacts.
- Deterministic validation occurs before a proposal is exposed to the caller.

The service does not claim that a proposal remains valid against changing external state after session initialization. Revalidation and conflict handling at persistence time belong to the consuming domain service and are outside this concept.

## Session Lifecycle

Short-lived service state is required so a proposal identifier can be resolved without trusting the model or requiring it to reconstruct recipe content. The state includes the initialization snapshots, ordered conversation content, validated proposals, and lineage. The backend exposes session-scoped proposal lookup by identifier.

Session expiry, maximum context, proposal count, and storage mechanism are implementation decisions. Expiry is visible when an expired session is first encountered; after its state is removed, later lookups may return unknown. Durable conversation history, session reopening, and recovery of expired proposals are out of scope.

## Reusable Chat UI

The AI Service provides a reusable chat UI that Kochwiki can integrate into its existing application. It owns generic conversation concerns, including ordered messages, sending and cancellation, streamed content, errors, session expiry, and placement of structured proposal artifacts within assistant turns.

The chat UI must not import Kochwiki components or understand Kochwiki recipe presentation. Instead, it exposes a typed renderer registry or equivalent host extension point:

- the host associates the recipe-proposal artifact type with its renderer;
- the chat UI invokes that renderer for validated proposal artifacts;
- the renderer receives typed proposal data and only explicitly supplied host actions;
- an absent or unsupported renderer produces a generic fallback rather than breaking the conversation; and
- registering a renderer does not grant the backend or model additional domain permissions.

Building the Kochwiki proposal renderer and deciding its visual treatment are deferred. The renderer contract is not deferred because proposal artifacts and chat state must let a host renderer consume structured content without reconstructing it from conversational text.

The chat UI is exposed as a reusable Angular library owned by the AI Service repository and consumed by Kochwiki at build time. This gives the current Angular host typed renderer injection without introducing an iframe boundary. The package registry, publication automation, release workflow, and local cross-repository development mechanism are deferred until Kochwiki needs to consume the library.

The library must retain a deliberately narrow public API so its packaging does not expose internal backend DTOs or make Kochwiki depend on private chat implementation details. A separately hosted iframe is not the assumed starting point because it complicates direct use of host-owned renderers and actions.

## Integration Impact

The AI Service backend exposes a recipe-improvement contract around session initialization, conversational turns, structured proposal artifacts, proposal lookup, and session expiry. External recipe and foodstuff identifiers remain opaque to the service.

The caller must supply a self-consistent recipe and foodstuff snapshot and translate returned proposals into its domain workflow. The AI Service does not read from or write to Kochwiki, create drafts, render recipes, or decide whether an external recipe changed.

Provider-specific model behavior stays behind the service's model abstraction. The structured proposal boundary and deterministic validation must not depend on a particular provider.

The reusable chat UI consumes the provider-neutral AI Service contract and exposes typed integration points to its host. Kochwiki supplies its proposal renderer to the chat UI, not to the AI Service backend.

## Scope Boundaries

In scope:

- one-recipe, short-lived improvement sessions;
- caller-provided recipe and foodstuff snapshots;
- generic recipe-improvement guidance shaped by user-stated goals and constraints;
- clarification and iterative conversational refinement;
- complete, structured proposals using available foodstuffs only;
- deterministic proposal identity, lineage, and validation;
- a reusable chat UI for the session lifecycle; and
- a typed extension point for host-supplied proposal renderers.

Out of scope:

- the Kochwiki-specific proposal renderer and its visual design;
- Kochwiki authorization, drafts, publication, and persistence;
- fetching recipes or foodstuffs directly from Kochwiki;
- foodstuff lookup tools in the initial capability;
- proposing or creating unavailable foodstuffs;
- durable chat history or session resumption;
- diagnosis, treatment, medical advice, or health-outcome claims;
- handling changes to the external source recipe during a session; and
- defining or guaranteeing specific dietary or medical optimization criteria.

## Risks

- Supplying the full foodstuff catalogue can consume excessive model context as the catalogue grows. A measured limit and a later lookup tool will be needed before this becomes unbounded.
- Catalogue entries may not contain enough semantic or nutritional information for the model to choose useful substitutions.
- Health-related suggestions can be mistaken for medical advice; the instructions and product language need clear limits.
- Short-lived state adds expiry and horizontal-scaling concerns even though durable persistence is excluded.
- A reusable chat UI can become coupled to Kochwiki if artifact or action APIs encode recipe-specific behavior instead of generic extension points.
- Deferring the concrete renderer while defining its contract risks discovering missing data later; the first contract should be exercised with a minimal test renderer.
- Deferring distribution avoids premature registry work, but the library must still be built as an independently consumable boundary so publication does not later require architectural separation.

## Open Questions

- What minimum recipe and foodstuff fields are required for useful and valid proposals?
- What catalogue-size or token-budget threshold triggers a move from an upfront snapshot to lookup tools?
- How long should a session live, and should activity extend its expiry?
- Which registry and release workflow should distribute the Angular chat UI library when Kochwiki integration begins?
- What generic renderer interface and fallback representation are sufficient for recipe proposals?
- Which host actions, if any, must the renderer contract anticipate before Kochwiki persistence work begins?

## Summary

The AI Service owns a short-lived, recipe-scoped improvement session that turns caller-supplied snapshots into validated recipe proposals. It also owns a reusable, embeddable chat UI that places typed proposals in the conversation and accepts their renderer from the host application. The initial capability uses generic instructions and is restricted to available foodstuffs. The Kochwiki renderer, domain persistence, and changing external state remain outside the service boundary.
