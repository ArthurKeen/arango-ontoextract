# PSI CRO demo — corpus provenance manifest

**Retrieved:** 2026-09-16 · **Manifest written:** 2026-09-17

Provenance for the clinical-research demonstrator corpus. The files themselves are
**not** in this repository: they are third-party publications under their own terms,
and 6.5 MB of PDFs do not belong in git. This manifest makes the corpus reproducible
without redistributing it.

> **Everything here is public.** No PSI material, no customer data, no patient data.
> Any run against PSI's own documents is a separate exercise under their agreement,
> not this one.

**Working copy:** `~/psi-demo-corpus/` (outside the repo, with a `SHA256SUMS` file).
**Ingested copies:** in AOE on `prod.demo.pilot.arango.ai` / `OntoExtract` — note that
AOE retains extracted text and chunks only, **not the source bytes**, so this manifest
is the only route back to the originals.

---

## Source documents

| File | Pages | Source | SHA-256 (first 16) |
|---|---:|---|---|
| `ich-m11-template.pdf` | 67 | [ICH M11 CeSHarP template, Step 4 final](https://database.ich.org/sites/default/files/ICH_Step4_M11_Final_Template_2025_1119.pdf) | `89ee5c3f5ff24cb6` |
| `ema-m11-template.pdf` | 63 | [EMA M11 CeSHarP template, Step 5](https://www.ema.europa.eu/en/documents/template-form/ich-m11-clinical-electronic-structured-harmonised-protocol-cesharp-template-step-5_en.pdf) | `fb6285950dfc3962` |
| `ich-e6r3-gcp.pdf` | 86 | [ICH E6(R3) Good Clinical Practice, Step 4 final](https://database.ich.org/sites/default/files/ICH_E6%28R3%29_Step4_FinalGuideline_2025_0106.pdf) | `e6ce19e36ce7d2e2` |
| `ixekizumab-Prot_000.pdf` | 111 | [NCT02696798 study protocol](https://cdn.clinicaltrials.gov/large-docs/98/NCT02696798/Prot_000.pdf) | `35a8f224abe94856` |
| `ixekizumab-SAP_001.pdf` | 187 | [NCT02696798 statistical analysis plan](https://cdn.clinicaltrials.gov/large-docs/98/NCT02696798/SAP_001.pdf) | `2aa2bdca6017a52b` |

**Why these five.** ICH M11 is the structure protocols are converging on — it came into
force 11 June 2026, so a CRO is living it now. ICH E6(R3) supplies the process and role
vocabulary a CRO recognises as its own job: sponsor, investigator, monitor, IRB/IEC.
The Ixekizumab protocol and its SAP are a *matched pair from one real trial*, which is
what makes the extracted ontology connect rather than fragment.

The EMA M11 template is a near-duplicate of the ICH one and was **deliberately held back**
from ingestion: two copies of the same template produce redundant classes and a worse
graph. It is kept here only as the regulator-published variant.

---

## Reference ontologies

| File | Source | SHA-256 (first 16) | Used |
|---|---|---|---|
| `cto.owl` | [Clinical Trials Ontology](http://purl.obolibrary.org/obo/cto.owl) | `9eb6c989f26ed907` | converted, then imported |
| `cto-rdfxml.owl` | derived from the above | `9214126826ca008c` | **imported as `cto`** — 298 classes |
| `obi-base.owl` | [OBI base](http://purl.obolibrary.org/obo/obi/obi-base.owl) | `684daab57bfd4f3b` | **not used** |

**CTO ships as OWL/XML, which AOE cannot import.** rdflib assumes RDF/XML and fails with
`Repeat node-elements inside property elements`. Converted with `owlready2` in a throwaway
venv — hence the two CTO files. This is a real product gap: a chunk of the OBO library and
plenty of vendor exports are OWL/XML, and a customer handing you one today gets a parse error.

**OBI was downloaded and rejected.** 4,993 classes overwhelmingly weighted to bench assays
(*"1M7 RNA structure mapping assay"*) would have buried the clinical concepts on the canvas.

**CDISC terminology could not be obtained.** NCI's EVS site is now an Angular app that
returns its HTML shell for every `ftp1/CDISC/...` path, `SDTM Terminology.owl` included;
BioPortal requires an API key. CDISC CT is what PSI will actually ask about, so it needs a
credentialed route (the CDISC Library API), not a scrape.

---

## Reproducing the corpus

```bash
mkdir -p ~/psi-demo-corpus/{corpus,ontologies} && cd ~/psi-demo-corpus

curl -sL -o corpus/ich-m11-template.pdf \
  "https://database.ich.org/sites/default/files/ICH_Step4_M11_Final_Template_2025_1119.pdf"
curl -sL -o corpus/ema-m11-template.pdf \
  "https://www.ema.europa.eu/en/documents/template-form/ich-m11-clinical-electronic-structured-harmonised-protocol-cesharp-template-step-5_en.pdf"
curl -sL -o corpus/ich-e6r3-gcp.pdf \
  "https://database.ich.org/sites/default/files/ICH_E6%28R3%29_Step4_FinalGuideline_2025_0106.pdf"
curl -sL -o corpus/ixekizumab-Prot_000.pdf \
  "https://cdn.clinicaltrials.gov/large-docs/98/NCT02696798/Prot_000.pdf"
curl -sL -o corpus/ixekizumab-SAP_001.pdf \
  "https://cdn.clinicaltrials.gov/large-docs/98/NCT02696798/SAP_001.pdf"

curl -sL -o ontologies/cto.owl "http://purl.obolibrary.org/obo/cto.owl"
# CTO is OWL/XML; convert before importing:
python -m venv /tmp/owlconv && /tmp/owlconv/bin/pip install -q owlready2
/tmp/owlconv/bin/python -c "import owlready2, os; \
o=owlready2.get_ontology('file://'+os.path.abspath('ontologies/cto.owl')).load(); \
o.save(file='ontologies/cto-rdfxml.owl', format='rdfxml')"

shasum -a 256 -c SHA256SUMS      # verify against the recorded hashes
```

Regulators revise these documents. A hash mismatch means the publication changed, not
that the download failed — re-record rather than force the old file.

---

## Licensing and redistribution

| Source | Consideration |
|---|---|
| ICH (M11, E6(R3)) | ICH publications carry their own copyright terms. Link; do not redistribute. |
| EMA | Reusable under EMA's terms with attribution. |
| ClinicalTrials.gov | US public domain; protocol/SAP posted by the sponsor under FDAAA. |
| CTO / OBI | OBO Foundry, open licences (CC-BY family). Check the individual ontology header. |

**Deliberately excluded: SNOMED CT and MedDRA.** Both are licensed, and MedDRA in
particular is exactly what a CRO will ask about. Naming them and saying "licensed — we
align to them once you hold a licence" is a stronger answer than quietly using them.

---

## Related

- `scripts/benchmarks/relationship_recovery.py` — measurement harness
- `docs/RESEARCH-clinical-data-standards.md` — why alignment, not authorship
- `docs/PROPOSAL-hybrid-lexical-matching.md` — the matching work this corpus exposed
