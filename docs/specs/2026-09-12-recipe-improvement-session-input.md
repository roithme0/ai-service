# Recipe Improvement Session Input

Status: implemented
Date: 2026-09-12
Related concept: ../concepts/2026-09-11-ai-assisted-recipe-improvement.md
Related specs: 2026-09-12-recipe-proposal-validation-boundary.md

## Outcome

The recipe-improvement capability has a validated, immutable internal input containing one complete source recipe and the foodstuffs available for proposals. Later session and model work can consume that input and its derived availability-reference index without trusting raw caller data.

## Scope

- Define and validate the internal session-initialization input and its foodstuff snapshot.
- Derive the existing proposal validator's availability-reference index from accepted foodstuffs.
- Do not create a session, invoke a model or tool, expose an HTTP endpoint, or retain state.

## Experience and UI Direction

Not applicable — this slice changes only an internal backend boundary.

## Decisions and Behavior

- Accept exactly one source recipe snapshot using the existing complete recipe-content structure. At this session boundary, its external reference must be a valid recipe-version UUID, represented as a string. The standalone proposal validator's existing opaque, non-empty source-reference contract remains unchanged.
- Each available foodstuff has a positive integer external reference, non-empty name of at most 50 characters, optional brand of at most 100 characters, and unit `G`, `ML`, or `PIECE`. These fields correspond to Kochwiki's current foodstuff identity and choice data; the AI Service does not fetch or own them.
- Nutrition fields, verbose unit labels, recipe-version usage, and other Kochwiki metadata are not part of this snapshot. Nutrition-targeted optimization is out of scope.
- Accept at most 100 foodstuffs, including an empty snapshot when the source has no ingredients. Reject duplicate foodstuff references. The limit is a simple guard for the initial snapshot approach, not a token-budget policy or commitment to keep full snapshots as the eventual integration.
- Reject a source ingredient whose foodstuff reference is absent from the snapshot, using the existing proposal-validation rules. Reject malformed source or foodstuff input with field-specific input failures; do not produce a partially accepted input or silently repair it.
- On success, expose the validated source, validated foodstuffs, and an availability-reference index derived solely from those foodstuffs. The accepted input must not change if the caller mutates its original lists or records afterward.
- This boundary does not decide whether a foodstuff is suitable for irritable bowel syndrome or whether a source recipe is medically appropriate.

## Contract

This is an internal, typed backend contract, not a network API. The success result is a self-consistent session input plus the derived index used by the existing validator. Failure is explicitly an input failure with locations identifying invalid fields or references. No session ID, expiry, conversation, optimization provenance, proposal identity, or artifact is produced.

## Constraints

- Keep the boundary provider-neutral and independent of Kochwiki runtime imports, database access, and live catalogue lookup.
- No dependency, build, tooling, frontend, or deployment change is required.

## Acceptance Criteria

1. A valid source with a recipe-version UUID and no more than 100 uniquely referenced foodstuffs yields an immutable, typed input and an index containing exactly those references.
2. Unknown source-ingredient references, malformed UUIDs, invalid foodstuff fields or units, duplicate references, and more than 100 foodstuffs fail as input errors with useful locations.
3. An empty foodstuff snapshot succeeds only when the source has no ingredient references.
4. Mutating the raw caller input after validation cannot change the accepted snapshot or its derived index.
5. The boundary performs no HTTP, UI, model, tool, or persistent-state action and makes no nutrition or medical judgment.

## Risks

- The 100-item ceiling is provisional and may reject a larger catalogue. Tool-based bounded lookup is the preferred later direction; this slice does not design it.
- Names, brands, and units may prove insufficient for useful substitutions. That concern belongs to later capability and tool-contract work, not structural initialization.
