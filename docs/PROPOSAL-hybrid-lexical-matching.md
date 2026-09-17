# Proposal — hybrid lexical + vector matching for alignment and resolution

**Status:** proposal, for review. Nothing implemented.
**Date:** 2026-09-16
**Origin:** measurements taken while preparing the PSI CRO demo (see §1).

> **The short version.** Every place AOE matches one concept to another does it with
> exact-or-nothing string comparison. There is no stemming, no tokenisation, no term
> weighting anywhere in the codebase. We should add a lexical tier — and we should
> almost certainly do it by adopting `arango-entity-resolution`, which already ships
> BM25, vector and **hybrid** blocking strategies and is already a declared AOE
> dependency, rather than building our own.

---

## 1. The evidence that prompted this

All measured on 2026-09-16 against live data, not estimated.

| Observation | Number |
|---|---|
| Parent resolution: URI fragments matched against a label-keyed dict | **8 hits in 363** |
| Alignment candidates generated for one 363-class ontology vs CTO (298) | **783** |
| …of which the LLM adjudicator rejected outright | **528 (67%)** |
| LLM calls to reach that verdict | **783**, ~15 minutes |
| Highest combined score in the entire session | **0.678** |
| Auto-accept band that score must clear | **0.92** |
| Unresolved parents naming a concept in plain words | **131** |

Three distinct symptoms, one cause.

**The auto-accept path is dead.** The scoring formula is label 0.4 + description 0.2 +
embedding 0.4. CTO's descriptions are sparse, so the description component scores ~0.03
even on a perfect pair — *Adverse Event* ↔ *adverse event* has label similarity 1.00 and
still totals 0.678. Nothing can reach 0.92, so "selective" adjudication is exhaustive:
every candidate costs an LLM call.

**Exact matching cannot see obvious pairs.** *"Adverse Events of Special Interest"* and
*"adverse event"* required an LLM to connect. Stemming plus token overlap ranks that pair
near the top for nothing.

**131 parents name a real concept in words and resolve against nothing**, because the
label tier is a normalised longest-match rather than an analysed one.

---

## 2. What AOE does today

| Site | Method | Weakness |
|---|---|---|
| `alignment._prefiltered_pairs` | embedding top-k, or full cross-product | no lexical signal at all |
| `alignment` scoring | label 0.4 / description 0.2 / embedding 0.4 | description weight is dead weight on sparse references |
| `edge_repair.resolve_range_class` | uri → fragment → normalised label → miss | no stemming, no tokens, no ranking |
| parent resolution | (as above, since 2026-09-16) | inherits the same ceiling |

Everything lexical is string equality after normalisation. That is the gap.

---

## 3. Do not build this — AER already has it

`arango-entity-resolution` is **already a declared AOE dependency** (`>=0.1`, 3.5.1
installed) and is currently used for exactly three MCP tools. Its blocking strategies are
importable from AOE's venv *right now* — verified:

```
entity_resolution.strategies.bm25_blocking      available
entity_resolution.strategies.vector_blocking    available
entity_resolution.strategies.hybrid_blocking    available
```

`hybrid_blocking.py`'s own docstring describes precisely the design this proposal was
going to argue for:

> *"Uses ArangoSearch BM25 for fast initial candidate generation, then verifies with
> Levenshtein distance for accuracy… BM25: Fast fuzzy text search (400x faster than
> Levenshtein alone)."*

It also ships `lsh_blocking`, `graph_traversal_blocking`, `graph_embedding_blocking`,
`shard_parallel_blocking`, and a **Fellegi–Sunter scorer** — the classical probabilistic
record-linkage model, which is a far better-founded way to combine match signals than our
hand-weighted 0.4/0.2/0.4.

Ontology alignment *is* record linkage: two sets of entities, block to candidates, score
pairs, adjudicate, and let a human confirm. We have been building a parallel, weaker
implementation of a problem a sibling library solves properly.

---

## 4. Proposed direction

**Adopt AER's blocking for candidate generation; keep AOE's semantics for adjudication.**
This is the same boundary argued in the portfolio architecture note — consume the library
for mechanism, own the meaning.

1. **Candidate generation → `HybridBlockingStrategy`.** Replace `_prefiltered_pairs` and
   `_full_product_pairs`. Expected effect: far fewer than 783 candidates reach the LLM,
   with better recall on stemmed variants.
2. **Add a lexical tier to `resolve_range_class`**, between fragment and normalised label,
   backed by the same ArangoSearch view. Targets the 131 plain-name parents.
3. **Re-derive the scoring weights**, ideally via Fellegi–Sunter rather than by hand. At
   minimum, stop letting a near-empty description field veto a perfect label match.
4. **Re-tune `alignment_auto_accept_band`** once scores are meaningful. A band no pair can
   reach is not a safety threshold, it is a switched-off feature.

### What this does *not* fix

Confabulated identifiers. A model that invents `obo:CTO_0000000` is not helped by better
search — though lexical recovery of the *fragment* (`directive_information_entity`) would
turn an invented citation into a resolvable one, which is a real secondary benefit. The
primary fix there is supplying real identifiers in the prompt context (done 2026-09-16).

---

## 5. Risks and unknowns

- **Version drift.** AOE has AER **3.5.1**; the repo is at **3.8.0**. The estate already
  has one unsatisfiable pin (`arango-cypher-py` vs `arango-sparql-py` on ASA). Any adoption
  must start by agreeing a band, not by importing whatever is installed.
- **Index maintenance during extraction.** An ArangoSearch view over `ontology_classes`
  must tolerate a collection that is written heavily and temporally versioned. View
  freshness against `expired` filtering needs testing, not assuming.
- **AER's strategies assume records, not ontology classes.** The adapter shape — what
  counts as a "field" for a class — is genuine design work, not glue.
- **Unmeasured.** No benchmark has been run. Every number in §1 describes the current
  system; none describes the proposed one. The first task is a spike, not an integration.

---

## 6. Suggested first step

A bounded spike, no production code: build an ArangoSearch view over the existing M11
extraction (363 classes) and CTO (298), run AER's hybrid blocking across them, and compare
against the recorded 783-candidate session — which is already in the database with full LLM
adjudications as ground truth.

That answers the only question that matters: **does hybrid blocking reproduce the 43
accepted correspondences while proposing far fewer than 783?** If it does, the integration
argues itself. If it doesn't, we have learned that cheaply.

---

## Appendix — evidence index

| Claim | Source |
|---|---|
| 8/363 fragment-vs-label hit rate | live query, M11 ontology `488213533` |
| 783 candidates, 528 rejected, 43 accepted | alignment session `5e3d59914f124d69a3bfea910d2129d0` |
| top score 0.678 vs band 0.92 | `settings.alignment_auto_accept_band`; session scores |
| AER strategies importable | `backend/.venv`, AER 3.5.1 |
| hybrid = BM25 + Levenshtein | `arango-entity-resolution/src/entity_resolution/strategies/hybrid_blocking.py` |
| AER repo at 3.8.0 vs 3.5.1 installed | `~/code/arango-entity-resolution/README.md`; `pip show` |
