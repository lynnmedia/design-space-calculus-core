# DSC Core RC1 bounded behavior specification v0.1

This versioned note describes the executable subset in this preview. It does not revise the frozen `novum-dsc/0.1` exchange contract, DSC-PL `language dsc 0.1`, or `DSC-IR-v0.1`.

## Representation and validation

DSC-PL source declares `language dsc 0.1`, targets `DSC-IR-v0.1`, and supplies an invention problem plus a seeded search block. The compiler parses source, checks declarations and references, applies the existing typed IR rules, and emits canonical JSON. The validator checks package conformance and reports controlled diagnostics for invalid source or IR. Canonical payload, ordered trace, and semantic-state digests allow inspection of the representation and its history. They do not measure invention effectiveness.

The preview includes the existing typed transformation representation and compiler checks. It supplies no autonomous search, generator, candidate scoring, or Pareto-selection runtime. A compiler accepting a transformation is a correctness result for the frozen language and IR, not evidence that the transformation improves an outcome.

## `novum-dsc/0.1` supported importer subset

The importer requires the exact `contract` marker and top-level `problem`, `entities`, `relations`, `tensions`, and `mechanisms` sections. It validates shapes of the fields it consumes and plans lowered declaration and branch identities before writing a workspace. The first need has direct lowering; further needs are sidecar-preserved. Functions and constraints lower directly. Goals, assumptions, unknowns, tensions, and mechanisms lower structurally. A declared mechanism's `satisfies` relation can lower to a substitution branch. Unsupported entity kinds, other relations, obligations, evidence, and provenance remain in a sidecar ledger and the complete source snapshot.

Identity collisions are rejected without renaming or merging sources. Rendering and compilation happen before workspace commit; a failed import leaves no new destination or success ledger. An existing destination is retained if failed `--force` import validation or staging occurs. Source identifiers and body text must still compile as DSC-PL. Additional fields in the source snapshot gain no executable meaning.

The ledger's zero-loss value means source records were accounted for, including sidecar preservation. It does not imply full executable semantic equivalence, arbitrary Novum graph execution, or interoperability across untested versions. The synthetic specimen in `examples/novum-success.json` exercises both lowering and sidecar classes without the Novum package.
