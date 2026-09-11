# AI-assisted Recipe Improvement

## Status

Draft. Defines the AI Service backend and reusable chat UI for bounded recipe improvement. The wider product flow and Kochwiki responsibilities remain documented in the neighboring planning repository.

## Context

The AI Service should provide a focused chat capability that improves one complete recipe through a short-lived conversational session. The caller supplies the source recipe and all foodstuffs currently available for proposals. The service applies a versioned irritable-bowel-syndrome-focused gut-health optimization capability and returns explainable, structured recipe proposals.

This concept covers AI orchestration, proposal production, short-lived conversation state, and a reusable chat UI that can be embedded into Kochwiki. Kochwiki remains responsible for recipe data, foodstuff data, authorization, domain-specific proposal presentation, validation at its boundary, and persistence through its own draft lifecycle.

## Decision

Introduce recipe improvement as a bounded, stateful AI Service capability rather than as unrestricted general chat.

Each session:

- is initialized with one complete source-recipe snapshot and its opaque external reference;
- receives a snapshot of the foodstuffs available for use in proposals;
- applies the irritable-bowel-syndrome-focused gut-health direction with an explicit version;
- supports clarification, questions, and iterative proposal refinement;
- retains its conversation, proposals, and proposal lineage in short-lived AI Service state; and
- expires without becoming durable recipe or chat storage.

The service produces immutable, complete recipe proposals. It assigns proposal identifiers, ordering, timestamps, base references, and optimization provenance deterministically. The model supplies conversational content, explanations, and structured recipe candidates but does not invent lifecycle metadata.

The AI Service also owns generic chat UI behavior. The UI presents conversational content and proposal placement but delegates proposal rendering to a renderer supplied by the host application.

## Foodstuff Boundary

The initial capability may use only foodstuffs included in the caller-provided availability snapshot. A proposal ingredient references an available foodstuff by its opaque external identifier. The proposal validator rejects unknown references before emitting an artifact.

Providing the availability snapshot up front is intentionally the first integration. It keeps foodstuff discovery deterministic and avoids granting the model a domain lookup capability. This is appropriate while the Kochwiki catalogue remains small enough to fit within an explicitly configured context budget.

Later iterations may replace or supplement the snapshot with a bounded foodstuff search or lookup tool. Proposing a foodstuff that does not yet exist, creating foodstuffs, and resolving free-text ingredients into new catalogue entries are out of scope.

The snapshot represents allowed references, not AI Service-owned domain data. It should contain only the fields needed to choose and explain an ingredient. The exact schema and catalogue-size limit remain contract-design questions.

## Initial Optimization Direction

The initial and only optimization direction is gut-health recipe improvement for a user with a diagnosed irritable bowel syndrome (German: `Reizdarm`). It is implemented as a versioned capability module that will provide instructions, evaluation criteria, and proposal strategies.

The concrete meaning of this optimization is deliberately deferred. This concept does not yet choose nutritional signals, symptom profiles, dietary protocols, scoring rules, or deterministic validation beyond structural proposal validity. Those decisions require a separate evidence-informed definition before implementation.

The capability improves recipes within the eventual criteria but does not diagnose, treat, or claim to improve the underlying condition. Its language and explanations must distinguish recipe suggestions from personalized medical advice.

Other optimization directions, including protein, calorie, and macronutrient targets, are outside the initial concept.

## Proposal Behavior

- A proposal contains the complete recipe content needed by the caller, not a patch.
- Every ingredient must reference the session's availability snapshot.
- A proposal identifies the source recipe or an earlier session proposal as its base.
- One assistant turn may emit multiple proposals when alternatives are requested.
- Each proposal includes a concise explanation of material changes and their relationship to the gut-health direction.
- The applied direction identifier and version are retained as provenance.
- Deterministic validation occurs before a proposal is exposed to the caller.

The service does not claim that a proposal remains valid against changing external state after session initialization. Revalidation and conflict handling at persistence time belong to the consuming domain service and are outside this concept.

## Session Lifecycle

Short-lived service state is required so a proposal identifier can be resolved without trusting the model or requiring it to reconstruct recipe content. The state includes the initialization snapshots, ordered conversation content, validated proposals, lineage, and capability provenance.

Session expiry, maximum context, proposal count, and storage mechanism are implementation decisions. Expiry must be visible to callers, and an expired proposal identifier must fail explicitly. Durable conversation history, session reopening, and recovery of expired proposals are out of scope.

## Reusable Chat UI

The AI Service provides a reusable chat UI that Kochwiki can integrate into its existing application. It owns generic conversation concerns, including ordered messages, sending and cancellation, streamed content, errors, session expiry, and placement of structured proposal artifacts within assistant turns.

The chat UI must not import Kochwiki components or understand Kochwiki recipe presentation. Instead, it exposes a typed renderer registry or equivalent host extension point:

- the host associates the recipe-proposal artifact type and version with its renderer;
- the chat UI invokes that renderer for validated proposal artifacts;
- the renderer receives typed proposal data and only explicitly supplied host actions;
- an absent or unsupported renderer produces a generic fallback rather than breaking the conversation; and
- registering a renderer does not grant the backend or model additional domain permissions.

Building the Kochwiki proposal renderer and deciding its visual treatment are deferred. The renderer contract is not deferred because proposal artifacts and chat state must let a host renderer consume structured content without reconstructing it from conversational text.

The chat UI is exposed as a reusable Angular library owned by the AI Service repository and consumed by Kochwiki at build time. This gives the current Angular host typed renderer injection without introducing an iframe boundary. The package registry, publication automation, release workflow, and local cross-repository development mechanism are deferred until Kochwiki needs to consume the library.

The library must retain a deliberately narrow public API so its packaging does not expose internal backend DTOs or make Kochwiki depend on private chat implementation details. A separately hosted iframe is not the assumed starting point because it complicates direct use of host-owned renderers and actions.

## Integration Impact

The AI Service backend exposes a versioned recipe-improvement contract around session initialization, conversational turns, structured proposal artifacts, and session expiry. External recipe and foodstuff identifiers remain opaque to the service.

The caller must supply a self-consistent recipe and foodstuff snapshot and translate returned proposals into its domain workflow. The AI Service does not read from or write to Kochwiki, create drafts, render recipes, or decide whether an external recipe changed.

Provider-specific model behavior stays behind the service's model abstraction. The structured proposal boundary and deterministic validation must not depend on a particular provider.

The reusable chat UI consumes the provider-neutral AI Service contract and exposes typed integration points to its host. Kochwiki supplies its proposal renderer to the chat UI, not to the AI Service backend.

## Scope Boundaries

In scope:

- one-recipe, short-lived improvement sessions;
- caller-provided recipe and foodstuff snapshots;
- the versioned irritable-bowel-syndrome-focused gut-health direction;
- clarification and iterative conversational refinement;
- complete, explainable, structured proposals using available foodstuffs only;
- deterministic proposal identity, lineage, provenance, and validation;
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
- optimization directions other than the initial gut-health direction;
- handling changes to the external source recipe during a session; and
- defining the detailed irritable-bowel-syndrome optimization criteria.

## Risks

- Supplying the full foodstuff catalogue can consume excessive model context as the catalogue grows. A measured limit and a later lookup tool will be needed before this becomes unbounded.
- Catalogue entries may not contain enough semantic or nutritional information for the model to choose useful substitutions.
- Irritable-bowel-syndrome guidance is individualized and medically sensitive. The eventual optimization definition and product language need evidence review and clear limits.
- Short-lived state adds expiry and horizontal-scaling concerns even though durable persistence is excluded.
- A reusable chat UI can become coupled to Kochwiki if artifact or action APIs encode recipe-specific behavior instead of generic extension points.
- Deferring the concrete renderer while defining its contract risks discovering missing data later; the first contract should be exercised with a minimal test renderer.
- Deferring distribution avoids premature registry work, but the library must still be built as an independently consumable boundary so publication does not later require architectural separation.

## Open Questions

- What evidence-informed definition should govern the irritable-bowel-syndrome-focused optimization?
- Which eventual criteria are deterministic, which depend on model judgment, and which are explanatory signals only?
- What minimum recipe and foodstuff fields are required for useful and valid proposals?
- What catalogue-size or token-budget threshold triggers a move from an upfront snapshot to lookup tools?
- How long should a session live, and should activity extend its expiry?
- Which registry and release workflow should distribute the Angular chat UI library when Kochwiki integration begins?
- What generic renderer interface and fallback representation are sufficient for the first proposal artifact version?
- Which host actions, if any, must the renderer contract anticipate before Kochwiki persistence work begins?

## Summary

The AI Service owns a short-lived, recipe-scoped optimization session that turns caller-supplied snapshots into validated and explainable recipe proposals. It also owns a reusable, embeddable chat UI that places typed proposals in the conversation and accepts their renderer from the host application. The initial capability is restricted to available foodstuffs and one versioned, irritable-bowel-syndrome-focused gut-health direction whose concrete criteria remain deferred. The Kochwiki renderer, domain persistence, and changing external state remain outside the service boundary.
