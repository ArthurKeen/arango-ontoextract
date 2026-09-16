"""Ontology IRI normalisation (PRD §6.2 FR-2.19).

Every class and property must carry an **absolute** IRI on a per-ontology base.
Two things go wrong without this, and both are silent:

* ``owl_serializer`` emits ``URIRef(cls.uri)`` verbatim, so a relative reference
  like ``namespace#Vehicle`` becomes invalid RDF the moment it is exported.
* §6.20 joins curated label decisions to concepts by ``concept_uri``. If two
  ontologies both emit ``namespace#Vehicle`` they share an identity they should
  not, so a rename in one silently applies to the other.

The observed failure was not a model being careless: the prompt's JSON schema
literally read ``"uri": "string (namespace#ClassName)"``, and an LLM copying a
placeholder it was shown is the expected outcome. The prompts are fixed, and
this is the belt to that braces — it also repairs ontologies extracted before
the fix.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import quote

#: Hosts reserved for documentation (RFC 2606). These are FLAGGED as weak
#: identities but NOT rewritten: they are valid, serialisable absolute IRIs, and
#: silently changing an identifier a user deliberately chose is worse than
#: leaving a documentation host in place. Rewriting is reserved for URIs that
#: genuinely cannot be used — see ``is_placeholder_uri``.
DOCUMENTATION_HOSTS = frozenset({"example.org", "www.example.org", "example.com", "namespace"})

_ABSOLUTE = re.compile(r"^https?://", re.IGNORECASE)


def base_namespace(ontology_id: str) -> str:
    """Per-ontology base IRI. Distinct per ontology so identities cannot collide."""
    return f"http://arango-ontoextract.local/ontology/{quote(ontology_id, safe='')}#"


def _local_name(uri: str, fallback: str) -> str:
    """The fragment/last segment of a URI, or a slug of ``fallback``."""
    tail = uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1].strip()
    if not tail:
        tail = fallback.strip()
    return quote(tail.replace(" ", ""), safe="") or "Unnamed"


#: Characters that make an IRI unserialisable by rdflib.
_ILLEGAL = re.compile(r"[\s<>\"{}|\\^`]")


def is_placeholder_uri(uri: str | None) -> bool:
    """True when the URI cannot serve as an identity and MUST be rewritten.

    Deliberately narrow. Two cases only:

    * **Relative** — ``namespace#Vehicle``, ``#Vehicle``, ``Vehicle``, empty.
      rdflib cannot serialise these, and identical relative references in two
      ontologies denote the same thing when they should not.
    * **Illegal characters** — a space or similar. The reported export failure
      was one value, ``namespace#qualifiedPersonnel Recommended``, taking down
      the whole file.

    A valid absolute IRI is LEFT ALONE even on a documentation host: it
    serialises correctly, and rewriting an identifier the user chose would
    silently break every reference to it. Use ``is_weak_identity`` to flag
    those for review instead.
    """
    if not uri or not uri.strip():
        return True
    u = uri.strip()
    if not _ABSOLUTE.match(u):
        return True
    return bool(_ILLEGAL.search(u))


def is_weak_identity(uri: str | None) -> bool:
    """True for a serialisable URI that is nonetheless a poor identity.

    Reportable (FR-2.19), not rewritten — an ontology on ``example.org`` still
    exports and round-trips; it just should not ship that way.
    """
    if is_placeholder_uri(uri):
        return True
    host = str(uri).strip().split("://", 1)[1].split("/", 1)[0].split("#", 1)[0].lower()
    return host in DOCUMENTATION_HOSTS


#: ArangoDB permits these in a ``_key`` (plus a 254-byte ceiling). Anything else
#: is replaced with ``-`` so a key stays insertable whatever the extractor emits.
_KEY_SAFE = re.compile(r"[^A-Za-z0-9_:.@()+,=;$!*'%-]")

#: Leave headroom under Arango's 254-byte ``_key`` limit for the separator and
#: the disambiguating digest appended to over-long keys.
_KEY_MAX = 240


def _key_segment(value: str) -> str:
    return _KEY_SAFE.sub("-", value.strip()) or "Unnamed"


def class_document_key(ontology_id: str, uri: str, *, label: str = "") -> str:
    """Storage ``_key`` for a class document, scoped to its ontology.

    The local name alone is NOT safe as a key. ``normalize_uri`` already scopes
    the *IRI* per ontology, but extraction used to key the document on just the
    IRI's fragment — so two ontologies extracted from the same document both
    wanted ``_key = "AdverseEventOfSpecialInterest"``. Combined with
    ``insert(..., overwrite=True)`` the second extraction silently took
    ownership of the first's class documents, re-stamping their ``ontology_id``
    and leaving the first ontology's ``subclass_of`` edges dangling — observed
    2026-09-16, where 14 of one ontology's 52 hierarchy edges pointed at classes
    the other run had claimed, and the effective graph dropped them.

    Scoping the key by ontology makes ``overwrite=True`` mean what it was always
    meant to mean: idempotent re-writes *within* one extraction, never across
    two. Existing ontologies keep their historical keys — nothing is rewritten,
    because their edges already reference them.
    """
    local = _local_name(uri, label)
    key = f"{_key_segment(ontology_id)}__{_key_segment(local)}"
    if len(key.encode("utf-8")) <= _KEY_MAX:
        return key
    # Truncating alone could collide two long names that share a prefix, so
    # carry a digest of the full identity.
    digest = hashlib.sha1(f"{ontology_id}#{local}".encode()).hexdigest()[:12]
    head = f"{_key_segment(ontology_id)[:90]}__{_key_segment(local)[:90]}"
    return f"{head}__{digest}"


def normalize_uri(uri: str | None, *, ontology_id: str, label: str) -> str:
    """Return ``uri`` if it is a usable absolute IRI, else rebuild it on the base.

    The local name is preserved where there is one, so ``namespace#Vehicle``
    becomes ``…/ontology/<id>#Vehicle`` rather than losing the term the
    extractor chose.
    """
    if not is_placeholder_uri(uri):
        return str(uri)
    return f"{base_namespace(ontology_id)}{_local_name(str(uri or ''), label)}"
