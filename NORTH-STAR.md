---
title: "Arango-OntoExtract — North Star"
type:
  - internal
  - vision
date: 2026-09-17
related:
  - "PRD.md (the near-term contract)"
  - "argos north star (~/code/argos/NORTH-STAR.md)"
  - "contextual-data-fabric north star (~/code/contextual-data-fabric/docs/contextual-data-fabric-north-star.md)"
  - "docs/RESEARCH-clinical-data-standards.md (alignment, not authorship)"
  - "docs/PROPOSAL-hybrid-lexical-matching.md"
status: draft
version: 0.1
---

# Arango-OntoExtract — North Star

> **Purpose:** the fixed point on the horizon every milestone ladders toward. The
> [PRD](PRD.md) is the near-term contract; this document is what the finished thing
> *is*. When a scope decision is ambiguous, check it against this.
>
> **Name caveat:** "OntoExtract" names the original capability. Extraction is now one
> acquisition path among four, and the majority of the system is curation, alignment,
> quality and versioning. The identifier is kept deliberately — repo, package, MCP
> server, and every provenance record across the estate are keyed on it, and an audit
> trail is a poor thing to break for a rename. This document describes the *thing*,
> not the name.

---

## The North Star (one sentence)

> **An organisation's ontology is a governed, living asset — acquired from whatever
> sources it already has, related to the vocabularies its industry has already
> standardised, changed only by decisions that are attributable, and answerable as of
> any moment in its history — so that what a term means, who decided it, and what it
> meant last quarter are all one query away.**

---

## The end state

**Ontologies arrive from wherever the knowledge is.** Documents, live graph schemas,
relational schemas, published standards, interchange artifacts from sibling tools.
Acquisition is plural and unremarkable; no source is privileged, and adding one is an
adapter, not a new product.

**Nothing is asserted because a machine said so.** Every class, property, relationship
and correspondence carries a confidence, the evidence it came from, and a status a
qualified human set or deliberately left unset. The machine proposes at scale; a person
disposes. A proposal that no one reviewed is visibly that, not silently fact.

**Nothing is lost, including what was wrong.** Every entity is versioned bitemporally:
when it was true of the source, and when the system learned it. A schema change ripples
visibly to the ontology terms and mappings that depend on it. "What did this mean in
June, and who changed it in July?" is a query, not an archaeology project.

**Your terms are related to the world's terms.** The industry has already published its
ontologies. The work is relating a customer's content to them — with per-correspondence
confidence, adjudication, and the direction of the relationship stated — not inventing a
parallel vocabulary. An extracted class hangs off the standard it specialises.

**The ontology is usable by everything else.** It leaves as OWL, SHACL and the
portfolio's interchange format, and it is ordinary queryable graph data while it is
here — alongside the documents, embeddings and search index it came from.

---

## Why this is the goal (the strategic thesis)

**Extraction is the cheapest part and getting cheaper.** Any competent model extracts
plausible concepts from a document. That capability commoditised while this project was
being built. What does not commoditise is everything that happens to a concept *after*
it is proposed: is it right, does it agree with the standard, who said so, what did it
used to be, and can you prove it.

**The buyers who care most are governed.** In clinical research, finance and safety
engineering, an ontology that cannot answer "who approved this term and when" is not
usable regardless of extraction quality. Bitemporal versioning and attributable curation
are not features there; they are admission criteria.

**Alignment, not authorship.** Customers rarely need a new ontology. They need their
content related to CDISC, FIBO, BFO, schema.org — vocabularies already published,
maintained and expected by their regulators. That is a smaller, more defensible and more
valuable claim than "we generate ontologies."

**The portfolio needs one system of record.** Sibling components acquire and consume:
the schema analyzers introspect sources, r2g maps, CDF federates queries, ArGOS governs
identity and provenance across tools. None of them owns an ontology through its life.
That is this component's job, and duplicating any of theirs is a mistake.

---

## What "winning" looks like

- A curator opens an ontology and can see, for any term, the passage it came from, the
  standard it maps to, the confidence, and every decision ever taken on it.
- A regulated customer passes an audit using the system's own history as evidence.
- A schema changes upstream and the affected terms are identified before anything breaks.
- A customer's extracted ontology is mostly *anchored* to published standards rather than
  free-floating — and the unanchored remainder is an explicit, worked queue.
- Another portfolio tool consumes a curated ontology without a bespoke integration.
- Someone asks "what did this mean six months ago?" and gets an answer in one query.

---

## Guiding principles

1. **The machine proposes; a qualified human disposes.** Automation that cannot be
   reviewed, overridden and attributed is not finished.
2. **Silence is a defect.** A pipeline stage that drops work must say how much. A success
   path that produces nothing must be distinguishable from one that had nothing to do.
3. **Own the semantics; consume the mechanism.** Acquisition, blocking, connectors and
   introspection come from libraries built for them. Meaning, curation, versioning and
   publication are ours.
4. **Identity is not a detail.** Two ontologies must never share an identifier, in the
   IRI or in storage. Ask a model to cite an identifier only if you supplied it.
5. **Never destroy intent.** Persist what was proposed even when it cannot be resolved.
   Unrecoverable intent is how a defect becomes invisible.
6. **The past is data.** Deletion is temporal by default. History is not housekeeping;
   it is the product.
7. **Measure on real sources.** Fixtures cannot show that 85% of proposed hierarchy is
   being discarded. Live counts can, and did.

---

## How today ladders to it

| Now | Toward |
|---|---|
| Four acquisition paths, unevenly mature | Acquisition is plural and unremarkable |
| Curation UI with status and confidence | Every change attributable to a named person (FR-20.3 is still open) |
| Bitemporal ontology entities | Bitemporal **schemas and mappings** too, so ripples are traceable |
| Alignment with LLM adjudication | Alignment good enough that anchoring is the norm, not the exception |
| OWL/SHACL export, CSI import | Full round trip: curated output consumed by the portfolio |

---

## What we are deliberately *not*

- **Not a hub.** Contextual Data Fabric is the metadata hub and federates queries; ArGOS
  is the governance plane. Claiming either would contradict a sibling's architecture and
  confuse the portfolio. This is a system of record and a workbench.
- **Not a reasoner.** Consistency checks and structural gates, not a general OWL DL
  reasoning engine.
- **Not a schema analyzer.** Source introspection belongs to the analyzers, and their
  output belongs to us.
- **Not a submission tool.** We report confidence and provenance; we do not assert
  regulatory conformance. The distinction matters most where it is most tempting to blur.
- **Not an autonomous curator.** Raising automation's ceiling is good; removing the human
  is not the goal.
