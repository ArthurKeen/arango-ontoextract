"""Schema-extraction failures must tell the user what to fix.

The endpoint takes a host, database name and credentials from a form and
then runs for ~50s against a remote cluster. It used to collapse every
failure into ``500 {"detail": "Internal server error"}``, so a typo'd
password and an unreachable cluster were indistinguishable from a real
bug -- and the only real explanation sat in a backend console.

The exception shapes asserted here were observed against a live
ArangoDB 3.12 cluster:

    wrong password    arango.exceptions.GraphListError  http_code=401
    missing database  arango.exceptions.GraphListError  http_code=404
    unreachable host  builtins.ConnectionAbortedError
"""

from __future__ import annotations

import pytest

from app.api.ontology.schema_temporal import _describe_extraction_failure
from app.services.schema_extraction import SchemaExtractionConfig

HOST = "https://cluster.example.com"


def _config(**kw: object) -> SchemaExtractionConfig:
    base: dict[str, object] = {
        "target_host": HOST,
        "target_db": "gdelt_market",
        "target_user": "root",
        "target_password": "secret-do-not-leak",
    }
    base.update(kw)
    return SchemaExtractionConfig(**base)  # type: ignore[arg-type]


class _UpstreamError(Exception):
    """Stand-in for an ArangoServerError subclass carrying an HTTP status."""

    def __init__(self, message: str, http_code: int) -> None:
        super().__init__(message)
        self.http_code = http_code


@pytest.mark.parametrize("code", [401, 403])
def test_rejected_credentials_are_a_400_naming_the_user(code: int) -> None:
    status, detail = _describe_extraction_failure(
        _UpstreamError("[HTTP 401][ERR 11] not authorized", code), _config()
    )
    assert status == 400
    assert "credentials" in detail
    assert "root" in detail and HOST in detail


def test_missing_database_is_a_400_naming_the_database() -> None:
    status, detail = _describe_extraction_failure(
        _UpstreamError("[HTTP 404][ERR 1228] database not found", 404), _config()
    )
    assert status == 400
    assert "gdelt_market" in detail and "does not exist" in detail


def test_missing_database_detected_from_message_without_http_code() -> None:
    status, detail = _describe_extraction_failure(
        Exception("[ERR 1228] database not found"), _config()
    )
    assert status == 400
    assert "gdelt_market" in detail


def test_unreachable_host_is_a_502() -> None:
    status, detail = _describe_extraction_failure(
        ConnectionAbortedError("Can't connect to host(s) within limit (3)"), _config()
    )
    assert status == 502
    assert HOST in detail


def test_unknown_failure_stays_500_but_names_the_exception_type() -> None:
    status, detail = _describe_extraction_failure(RuntimeError("kaboom"), _config())
    assert status == 500
    assert "RuntimeError" in detail
    assert "server log" in detail


@pytest.mark.parametrize(
    "exc",
    [
        _UpstreamError("[HTTP 401] not authorized", 401),
        _UpstreamError("[HTTP 404] database not found", 404),
        ConnectionAbortedError("Can't connect"),
        RuntimeError("kaboom"),
    ],
)
def test_no_failure_message_leaks_the_password(exc: Exception) -> None:
    """The config carries a password; none of these messages may echo it."""
    _, detail = _describe_extraction_failure(exc, _config())
    assert "secret-do-not-leak" not in detail
