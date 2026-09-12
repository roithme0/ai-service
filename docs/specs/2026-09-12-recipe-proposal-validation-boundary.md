# Recipe Proposal Validation Boundary

Status: implemented
Date: 2026-09-12
Related concept: ../concepts/2026-09-11-ai-assisted-recipe-improvement.md
Related specs: None

## Outcome

The AI Service has a typed, provider-independent boundary that accepts a complete recipe proposal candidate only when its content is structurally valid and every ingredient uses a foodstuff in the caller-supplied availability snapshot. Later model and session work can rely on this boundary without trusting model-generated references.

## Scope

- Define internal typed representations for one source recipe snapshot, an availability-reference index, and a complete proposal candidate.
- Validate the source snapshot, availability-reference index, and each candidate before it can become a proposal artifact.
- Return validated recipe content or explicit validation failures; do not silently repair a candidate.
- No HTTP endpoint, model invocation, session state, proposal identity or lineage, optimization criteria, nutrition evaluation, or Kochwiki integration in this slice.

## Experience and UI Direction

Not applicable — this is an internal backend validation boundary with no UI or frontend contract.

## Decisions and Behavior

- Use Kochwiki's current recipe-version content as the structural baseline: name, servings, optional preparation time and origin fields, ordered ingredients with amounts and foodstuff references, and ordered preparation steps. Source identity is an opaque external reference; Kochwiki lifecycle state, timestamps, ingredient row IDs, and derived nutrition are not recipe content here.
- The source snapshot includes its complete recipe content and external reference. The validator receives an index of unique foodstuff references derived from the caller's availability snapshot. This index is only a validation input: it does not define or replace the richer foodstuff snapshot needed by a later model-facing session contract.
- A candidate contains a complete replacement recipe, not a patch. It can change any recipe-owned content, including order, quantities, and steps, within the structural rules. It does not carry source identity, proposal identity, timestamps, provenance, or a base-proposal reference.
- Treat external foodstuff references as opaque values. In this first internal contract, accept Kochwiki's positive integer IDs without giving their numeric value meaning. An ingredient is invalid if its reference is absent from the availability-reference index, including when it appears in the source recipe.
- Apply the relevant Kochwiki write-shape limits: non-empty name up to 200 characters; servings 1–99; optional preparation time 1–999; optional origin name up to 200 characters; optional absolute origin URL up to 200 characters, with an empty URL normalized to absent; ingredient and step indexes 1–99 and unique within their respective lists; positive ingredient amounts no greater than 9999; non-empty step descriptions up to 200 characters. Preserve decimal quantities without floating-point conversion. Empty ingredient or step lists remain structurally valid, matching Kochwiki's current write contract.
- Reject duplicate foodstuff references within one recipe, even at different indexes, because Kochwiki's persistence model permits only one ingredient row per foodstuff per version. Ordering need not be contiguous; indexes determine order.
- Reject duplicate references in the availability-reference index. Report invalid source or index inputs separately from invalid candidates so callers cannot mistake a bad input boundary for model failure.
- Structural validation does not judge whether a recipe is helpful for irritable bowel syndrome, whether an ingredient is medically appropriate, or whether a candidate is an improvement over the source.

## Contract

This is an internal, typed backend contract, not a new network API. A successful validation yields the complete validated candidate content. Failures identify the invalid field or reference and do not yield a partial accepted candidate. Future session and artifact contracts may wrap this content with service-generated identity, ordering, lineage, and provenance.

## Constraints

- Kochwiki remains authoritative for persistence-time validation and current foodstuff existence; validation against the supplied snapshot does not guarantee later Kochwiki acceptance.
- Keep the boundary provider-neutral and independent of Kochwiki runtime imports or database access. No dependency or build/tooling changes are required by this spec.

## Acceptance Criteria

1. A complete candidate using only uniquely listed available foodstuffs and satisfying Kochwiki-aligned structural rules is accepted unchanged, including its decimal amounts and non-contiguous but unique indexes.
2. A candidate referencing a foodstuff outside the availability snapshot is rejected with a field-specific failure; no validated candidate is emitted.
3. Invalid source content, source ingredients outside the availability-reference index, or duplicate index references are rejected as input errors before candidates are evaluated.
4. Duplicate ingredient foodstuffs or indexes, duplicate step indexes, invalid amounts, and invalid required or optional recipe fields are rejected as candidate errors.
5. Empty ingredient or step lists remain valid, and validation makes no medical or nutritional claim.
6. The boundary has no HTTP, UI, model-provider, or persistent-state side effects.

## Risks

- Kochwiki's write schema currently allows duplicate foodstuff IDs even though its database forbids them. This boundary follows the database constraint; Kochwiki should eventually make its own write validation consistent.
- This slice proves structural safety only. The later model-facing foodstuff snapshot needs names, units, and perhaps nutrition or other evidence fields; those are intentionally not fixed here. The validation index must be derived from that snapshot when a session contract is introduced.
