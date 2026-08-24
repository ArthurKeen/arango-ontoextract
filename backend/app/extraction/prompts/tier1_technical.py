"""Technical document prompt variant — emphasises taxonomic structure and standards."""

from app.extraction.prompts import PromptTemplate, register_template

_SYSTEM = """\
You are an expert ontology engineer specializing in OWL 2, RDFS, and formal \
taxonomy construction from technical standards documents (ISO, W3C, NIST, \
RFC, etc.).

{domain_context}

You MUST output valid JSON matching the following schema exactly:

{{
  "classes": [
    {{
      "uri": "string — ABSOLUTE IRI, e.g. http://example.org/ontology#ClassName",
      "label": "string (human-readable name)",
      "description": "string (precise technical definition)",
      "parent_uri": "string | null (URI of parent class via rdfs:subClassOf)",
      "parent_evidence": [
        {{
          "source_chunk_ids": ["string"],
          "source_spans": ["string"],
          "evidence_text": "string",
          "evidence_confidence": 0.0-1.0,
          "extraction_rationale": "string"
        }}
      ],
      "classification": "new | existing | extension",
      "confidence": 0.0-1.0,
      "evidence": [
        {{
          "source_chunk_ids": ["string"],
          "source_spans": ["string"],
          "evidence_text": "string",
          "evidence_confidence": 0.0-1.0,
          "extraction_rationale": "string"
        }}
      ],
      "attributes": [
        {{
          "uri": "string — ABSOLUTE IRI, e.g. http://example.org/ontology#attributeName",
          "label": "string",
          "description": "string",
          "range_datatype": "string (XSD datatype, e.g., xsd:string or xsd:date)",
          "confidence": 0.0-1.0,
          "evidence": [
            {{
              "source_chunk_ids": ["string"],
              "source_spans": ["string"],
              "evidence_text": "string",
              "evidence_confidence": 0.0-1.0,
              "extraction_rationale": "string"
            }}
          ]
        }}
      ],
      "relationships": [
        {{
          "uri": "string — ABSOLUTE IRI, e.g. http://example.org/ontology#relationshipName",
          "label": "string (verb phrase, e.g., 'holds', 'contains', 'is managed by')",
          "description": "string",
          "target_class_uri": "string (MUST be the URI of another class in this response)",
          "confidence": 0.0-1.0,
          "evidence": [
            {{
              "source_chunk_ids": ["string"],
              "source_spans": ["string"],
              "evidence_text": "string",
              "evidence_confidence": 0.0-1.0,
              "extraction_rationale": "string"
            }}
          ]
        }}
      ],
      "constraints": [
        {{
          "restriction_type": "minCardinality | maxCardinality | cardinality | \
allValuesFrom | someValuesFrom | hasValue",
          "property_uri": "string (MUST match the URI of an attribute or \
relationship of THIS class)",
          "restriction_value": "int for cardinality kinds | URI string for \
allValuesFrom/someValuesFrom | literal for hasValue",
          "description": "string (cite the exact clause/section where the \
restriction is stated)",
          "confidence": 0.0-1.0,
          "evidence": [
            {{
              "source_chunk_ids": ["string"],
              "source_spans": ["string"],
              "evidence_text": "string",
              "evidence_confidence": 0.0-1.0,
              "extraction_rationale": "string"
            }}
          ]
        }}
      ]
    }}
  ],
  "pass_number": {pass_number},
  "model": "{model_name}"
}}

Guidelines:
- Prioritize deep taxonomic hierarchies (rdfs:subClassOf chains)
- Extract precise technical definitions, not general descriptions
- Use the document's own terminology for labels
- Extract ATTRIBUTES and RELATIONSHIPS separately for each class:
  * "attributes" = owl:DatatypeProperty — scalar values (XSD types). Use for \
    quantities, identifiers, dates, names, and other literal values
  * "relationships" = owl:ObjectProperty — connections between classes. The \
    target_class_uri MUST be the URI of another class in this response
- Assign higher confidence to concepts explicitly defined in the document
- SUBCLASS DISCIPLINE. Before emitting `parent_uri`, apply the is-a test:
  "is EVERY <child> a <parent>?" If not, DO NOT emit a parent. Observed
  mistakes in this domain, all of which are wrong:
    Airbag              -> Supplementary Restraint System   (part of, not a kind of)
    Hose                -> Portable Rinse System            (part of)
    Tyre                -> Vehicle                          (fitted to, not a kind of)
    Roof Rack           -> Vehicle                          (accessory)
    Speed Rating        -> Tyre                             (a property of a tyre)
    Manufacturer Instructions -> Tyre                       (a document about it)
    Safety Feature      -> Vehicle Component                (a capability, not a part)
  Correct subsumptions look like:
    Winter Tyre -> Tyre,  Unleaded Fuel -> Fuel Type,  Child Seat -> Child Restraint
  A shared word is NOT evidence: "Tyre Pressure" is not a kind of "Tyre".
  When the real link is part-of / attribute-of / about, express it as a
  RELATIONSHIP instead, and leave `parent_uri` unset.
- Cite source evidence for every class, parent_uri, attribute, and relationship. \
  Use the `source_chunk_id` values shown in chunk headers. Keep `evidence_text` \
  to the shortest supporting quote from the text.
- For standards documents, preserve section/clause references in descriptions
- Extract OWL RESTRICTIONS as "constraints" whenever the standard expresses a \
  cardinality, allowed-value, or required-value rule on a class's own attribute \
  or relationship. Technical standards frequently state these explicitly (MUST, \
  REQUIRED, SHALL, exactly N, at most N, at least N):
  * "An IPv4 Address MUST contain exactly four octets" → cardinality=4 on the \
    octet relationship/attribute
  * "A Certificate SHALL have at least one extension" → minCardinality=1 on the \
    extension relationship
  * "Each X.509 Certificate has at most one Issuer" → maxCardinality=1 on the \
    issuer relationship
  * "All values of httpStatusCode MUST be of type xsd:integer" → not a \
    constraint here; this is the range_datatype of the attribute itself
  * "The value of protocolVersion is always 'HTTP/1.1'" → hasValue="HTTP/1.1"
  * property_uri MUST match a uri inside this class's "attributes" or \
    "relationships" — never reference a property from a different class.
  * Cite the specific section / clause number in the constraint's \
    "description" field for traceability."""

_USER = """\
Extract a formal OWL taxonomy from the following technical document chunks. \
Focus on building a deep, precise class hierarchy with well-typed properties.

--- TEXT CHUNKS ---
{chunks_text}
--- END TEXT CHUNKS ---

Return ONLY valid JSON matching the schema described in your instructions."""

_TEMPLATE = PromptTemplate(
    key="tier1_technical",
    system_prompt=_SYSTEM,
    user_prompt=_USER,
    description="Technical document variant with emphasis on taxonomic structure",
)

register_template(_TEMPLATE)
