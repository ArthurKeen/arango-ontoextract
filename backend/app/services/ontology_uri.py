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


def normalize_uri(uri: str | None, *, ontology_id: str, label: str) -> str:
    """Return ``uri`` if it is a usable absolute IRI, else rebuild it on the base.

    The local name is preserved where there is one, so ``namespace#Vehicle``
    becomes ``…/ontology/<id>#Vehicle`` rather than losing the term the
    extractor chose.
    """
    if not is_placeholder_uri(uri):
        return str(uri)
    return f"{base_namespace(ontology_id)}{_local_name(str(uri or ''), label)}"
