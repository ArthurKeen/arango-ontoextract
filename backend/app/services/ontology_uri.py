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

#: Hosts that indicate a placeholder rather than a real namespace. ``example.org``
#: is reserved for documentation (RFC 2606), so it is a placeholder too — just a
#: better-behaved one than the literal word "namespace".
PLACEHOLDER_HOSTS = frozenset({"namespace", "example.org", "www.example.org", "example.com"})

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


def is_placeholder_uri(uri: str | None) -> bool:
    """True when the URI is unusable as an identity: relative, or a placeholder host."""
    if not uri or not uri.strip():
        return True
    u = uri.strip()
    if not _ABSOLUTE.match(u):
        # Anything not absolute — "namespace#Vehicle", "#Vehicle", "Vehicle".
        return True
    host = u.split("://", 1)[1].split("/", 1)[0].split("#", 1)[0].lower()
    return host in PLACEHOLDER_HOSTS


def normalize_uri(uri: str | None, *, ontology_id: str, label: str) -> str:
    """Return ``uri`` if it is a usable absolute IRI, else rebuild it on the base.

    The local name is preserved where there is one, so ``namespace#Vehicle``
    becomes ``…/ontology/<id>#Vehicle`` rather than losing the term the
    extractor chose.
    """
    if not is_placeholder_uri(uri):
        return str(uri)
    return f"{base_namespace(ontology_id)}{_local_name(str(uri or ''), label)}"
