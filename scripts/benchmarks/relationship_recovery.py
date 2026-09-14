#!/usr/bin/env python3
"""Measure how many relationships AOE recovers, with and without ASA/RSA.

Why this exists
---------------
AOE derives relationships from *declared* structure: foreign keys on the
relational side, edge collections on the graph side. When a source only
*implies* its relationships -- a ``customer_id`` column with no FK
constraint, a ``customer_id`` field with no edge -- AOE emits classes with
no ``owl:ObjectProperty`` between them at all. The result is an ontology of
disconnected entities, which for a graph tool is the difference between
useful and not.

``arangodb-schema-analyzer`` (ASA) and ``relational-schema-analyzer`` (RSA)
both ship relationship inference for exactly that case. This benchmark
builds fixtures in both shapes and reports what each path recovers, so the
"should AOE use these libraries" question is answered with numbers instead
of architecture opinion.

Measured 2026-09-10 on DuckDB 1.5.4 + ArangoDB 3.12 (identical data in
every fixture):

    relational   PK+FK declared      AOE 3   RSA 0   (already declared)
    relational   PK only, no FK      AOE 0   RSA 3   at 0.85
    relational   neither             AOE 0   RSA 0   <- see LIMITATION
    arango       edge collections    AOE 3   ASA 0   (already explicit)
    arango       join-style fields   AOE 0   ASA 3   at 0.90

LIMITATION worth knowing: with neither PK nor FK, RSA also finds nothing.
Its inference builds a key index and matches candidate columns against it,
so with no keys there are no candidates -- even though the values still
carry the signal (``orders.customer_id`` is a strict subset of
``customers.customer_id``). ``sample_overlap`` *confirms* name-based
candidates rather than *generating* them. That is the messiest real-world
case (CSV exports, legacy MyISAM, ad-hoc warehouse tables) and is an
enhancement opportunity in RSA, not a bug in this benchmark.

Usage
-----
    python scripts/benchmarks/relationship_recovery.py
    python scripts/benchmarks/relationship_recovery.py --skip-arango

Requires ``duckdb`` and ``relational-schema-analyzer`` (both already in the
backend venv). ASA is optional and NOT an AOE dependency -- install it into
a throwaway venv to include the graph half:

    python -m venv /tmp/asa && /tmp/asa/bin/pip install arangodb-schema-analyzer
    /tmp/asa/bin/python scripts/benchmarks/relationship_recovery.py --arango-only

Arango connection comes from --arango-url / --arango-user / --arango-password
(defaults suit a local dev container). Test databases are prefixed ``zz_bench_``
and dropped on exit.
"""

from __future__ import annotations

import argparse
import random
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

GRAPH_DB = "zz_bench_graph"
JOINS_DB = "zz_bench_joins"


# ---------------------------------------------------------------------------
# Relational fixtures
# ---------------------------------------------------------------------------

_TABLES_CONSTRAINED = """
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY, name VARCHAR, email VARCHAR, country VARCHAR);
CREATE TABLE products (
    product_id INTEGER PRIMARY KEY, sku VARCHAR, name VARCHAR, price DECIMAL(10,2));
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(customer_id),
    order_date DATE, total DECIMAL(10,2));
CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER REFERENCES orders(order_id),
    product_id INTEGER REFERENCES products(product_id),
    quantity INTEGER, unit_price DECIMAL(10,2));
"""

_TABLES_PK_ONLY = """
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY, name VARCHAR, email VARCHAR, country VARCHAR);
CREATE TABLE products (
    product_id INTEGER PRIMARY KEY, sku VARCHAR, name VARCHAR, price DECIMAL(10,2));
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY, customer_id INTEGER,
    order_date DATE, total DECIMAL(10,2));
CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER,
    quantity INTEGER, unit_price DECIMAL(10,2));
"""

_TABLES_BARE = """
CREATE TABLE customers (
    customer_id INTEGER, name VARCHAR, email VARCHAR, country VARCHAR);
CREATE TABLE products (
    product_id INTEGER, sku VARCHAR, name VARCHAR, price DECIMAL(10,2));
CREATE TABLE orders (
    order_id INTEGER, customer_id INTEGER, order_date DATE, total DECIMAL(10,2));
CREATE TABLE order_items (
    order_item_id INTEGER, order_id INTEGER, product_id INTEGER,
    quantity INTEGER, unit_price DECIMAL(10,2));
"""

RELATIONAL_FIXTURES = (
    ("PK + FK declared", _TABLES_CONSTRAINED),
    ("PK only, no FK", _TABLES_PK_ONLY),
    ("no PK, no FK", _TABLES_BARE),
)


def _build_duckdb(path: Path, ddl: str) -> None:
    import duckdb

    random.seed(7)  # identical data in every fixture, so only shape varies
    con = duckdb.connect(str(path))
    for stmt in filter(str.strip, ddl.split(";")):
        con.execute(stmt)
    con.executemany(
        "INSERT INTO customers VALUES (?,?,?,?)",
        [
            (i, f"Cust{i}", f"c{i}@example.com", random.choice(["US", "GB", "DE"]))
            for i in range(1, 51)
        ],
    )
    con.executemany(
        "INSERT INTO products VALUES (?,?,?,?)",
        [
            (i, f"SKU-{i:04d}", f"Product {i}", round(random.uniform(5, 500), 2))
            for i in range(1, 31)
        ],
    )
    con.executemany(
        "INSERT INTO orders VALUES (?,?,?,?)",
        [
            (i, random.randint(1, 50), "2026-01-01", round(random.uniform(20, 900), 2))
            for i in range(1, 201)
        ],
    )
    con.executemany(
        "INSERT INTO order_items VALUES (?,?,?,?,?)",
        [
            (
                i,
                random.randint(1, 200),
                random.randint(1, 30),
                random.randint(1, 5),
                round(random.uniform(5, 500), 2),
            )
            for i in range(1, 601)
        ],
    )
    con.close()


def _count_owl(ttl: str) -> tuple[int, int]:
    from rdflib import OWL, RDF, Graph

    g = Graph()
    g.parse(data=ttl, format="turtle")
    return (
        len(set(g.subjects(RDF.type, OWL.Class))),
        len(set(g.subjects(RDF.type, OWL.ObjectProperty))),
    )


def run_relational() -> list[tuple[str, int, int, int]]:
    """Return (fixture, aoe_classes, aoe_object_props, rsa_inferred) rows."""
    from relational_schema_analyzer import (
        create_connector,
        create_value_sampler,
        infer_foreign_keys,
    )
    from relational_schema_analyzer.fk_inference import InferenceOptions

    from app.services.relational_schema_extraction import (
        RelationalSchemaExtractionConfig,
        _introspect,
        build_relational_owl,
    )

    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for label, ddl in RELATIONAL_FIXTURES:
            path = Path(tmp) / f"{label.replace(' ', '_').replace(',', '')}.duckdb"
            _build_duckdb(path, ddl)

            cfg = RelationalSchemaExtractionConfig(
                source_type="duckdb",
                url=str(path),
                schema_name="main",
                db_label="bench",
            )
            physical, _source, db_label = _introspect(cfg)
            ttl = build_relational_owl(physical, db_label=db_label)
            if isinstance(ttl, tuple):
                ttl = ttl[0]
            classes, object_props = _count_owl(ttl)

            schema = create_connector("duckdb", str(path)).get_schema()
            inferred = infer_foreign_keys(
                schema,
                options=InferenceOptions(sample_overlap=True),
                sampler=create_value_sampler("duckdb", str(path)),
            )
            rows.append((label, classes, object_props, len(inferred)))
    return rows


# ---------------------------------------------------------------------------
# ArangoDB fixtures
# ---------------------------------------------------------------------------


def _build_arango(client: Any, user: str, password: str) -> None:
    random.seed(7)
    sys_db = client.db("_system", username=user, password=password)
    for name in (GRAPH_DB, JOINS_DB):
        if sys_db.has_database(name):
            sys_db.delete_database(name)
        sys_db.create_database(name)

    customers = [
        {
            "_key": f"c{i}",
            "name": f"Cust{i}",
            "email": f"c{i}@x.com",
            "country": random.choice(["US", "GB"]),
        }
        for i in range(1, 51)
    ]
    products = [
        {
            "_key": f"p{i}",
            "sku": f"SKU-{i:04d}",
            "name": f"Product {i}",
            "price": round(random.uniform(5, 500), 2),
        }
        for i in range(1, 31)
    ]

    # (a) relationships EXPLICIT: edge collections in a named graph
    g = client.db(GRAPH_DB, username=user, password=password)
    for v in ("Customer", "Product", "Order", "OrderItem"):
        g.create_collection(v)
    for e in ("placed", "contains", "refersTo"):
        g.create_collection(e, edge=True)
    graph = g.create_graph("shop")
    graph.create_edge_definition("placed", ["Customer"], ["Order"])
    graph.create_edge_definition("contains", ["Order"], ["OrderItem"])
    graph.create_edge_definition("refersTo", ["OrderItem"], ["Product"])
    g.collection("Customer").insert_many(customers)
    g.collection("Product").insert_many(products)
    g.collection("Order").insert_many(
        [
            {
                "_key": f"o{i}",
                "order_date": "2026-01-01",
                "total": round(random.uniform(20, 900), 2),
            }
            for i in range(1, 201)
        ]
    )
    g.collection("OrderItem").insert_many(
        [
            {
                "_key": f"oi{i}",
                "quantity": random.randint(1, 5),
                "unit_price": round(random.uniform(5, 500), 2),
            }
            for i in range(1, 601)
        ]
    )
    g.collection("placed").insert_many(
        [
            {"_from": f"Customer/c{random.randint(1, 50)}", "_to": f"Order/o{i}"}
            for i in range(1, 201)
        ]
    )
    g.collection("contains").insert_many(
        [
            {"_from": f"Order/o{random.randint(1, 200)}", "_to": f"OrderItem/oi{i}"}
            for i in range(1, 601)
        ]
    )
    g.collection("refersTo").insert_many(
        [
            {"_from": f"OrderItem/oi{i}", "_to": f"Product/p{random.randint(1, 30)}"}
            for i in range(1, 601)
        ]
    )

    # (b) relationships IMPLIED: reference fields, no edge collections at all
    j = client.db(JOINS_DB, username=user, password=password)
    for v in ("Customer", "Product", "Order", "OrderItem"):
        j.create_collection(v)
    j.collection("Customer").insert_many(customers)
    j.collection("Product").insert_many(products)
    j.collection("Order").insert_many(
        [
            {
                "_key": f"o{i}",
                "customer_id": f"c{random.randint(1, 50)}",
                "order_date": "2026-01-01",
                "total": round(random.uniform(20, 900), 2),
            }
            for i in range(1, 201)
        ]
    )
    j.collection("OrderItem").insert_many(
        [
            {
                "_key": f"oi{i}",
                "order_id": f"o{random.randint(1, 200)}",
                "product_id": f"p{random.randint(1, 30)}",
                "quantity": random.randint(1, 5),
            }
            for i in range(1, 601)
        ]
    )


def _asa_shapes(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build ASA ``CollectionShape`` objects from a physical snapshot.

    Not obvious, and getting it wrong reports a silent zero rather than an
    error -- two of the three attempts while writing this benchmark did
    exactly that. Two gotchas:

      * the snapshot's ``observed_fields`` is ``{"fields": [...]}``, a dict
        wrapping the list, while ``properties`` is *collection* metadata
        (``waitForSync`` etc.), not field names;
      * ``CollectionShape.fields`` must be a MAPPING of field -> type. Pass
        a list and inference dies deep inside ``_make_candidate`` with
        ``'list' object has no attribute 'get'``.
    """
    from schema_analyzer import CollectionShape

    def py_type(value: Any) -> str:
        return {str: "string", int: "integer", float: "number", bool: "boolean"}.get(
            type(value), "string"
        )

    shapes = {}
    for entry in snapshot["collections"]:
        fields: dict[str, str] = {}
        for doc in entry.get("sample_documents") or []:
            for key, value in doc.items():
                if not key.startswith("_"):
                    fields.setdefault(key, py_type(value))
        shapes[entry["name"]] = CollectionShape(
            name=entry["name"],
            fields=fields,
            key_fields=["_key"],
            unique_fields=[],
            sample_values={},
            count=entry.get("count") or 0,
        )
    return shapes


def run_arango(
    url: str, user: str, password: str
) -> list[tuple[str, int, int, int | None]]:
    """Return (fixture, aoe_classes, aoe_object_props, asa_inferred) rows."""
    from arango import ArangoClient

    client = ArangoClient(hosts=url)
    _build_arango(client, user, password)

    try:
        from schema_analyzer import ArangoValueSampler, infer_foreign_keys
        from schema_analyzer.fk_inference import InferenceOptions
        from schema_analyzer.snapshot import snapshot_physical_schema

        asa_available = True
    except ImportError:
        asa_available = False

    rows = []
    try:
        for dbname, label in (
            (GRAPH_DB, "edge collections"),
            (JOINS_DB, "join-style fields"),
        ):
            classes = object_props = 0
            try:
                from app.services.schema_extraction import (
                    SchemaExtractionConfig,
                    _direct_extract_schema,
                )

                cfg = SchemaExtractionConfig(
                    target_host=url,
                    target_db=dbname,
                    target_user=user,
                    target_password=password,
                    verify_tls=False,
                )
                ttl, _mapping = _direct_extract_schema(cfg)
                classes, object_props = _count_owl(ttl)
            except ImportError:
                classes = (
                    object_props
                ) = -1  # running under the ASA venv, no AOE backend

            inferred: int | None = None
            if asa_available:
                db = client.db(dbname, username=user, password=password)
                snapshot = snapshot_physical_schema(
                    db, sample_limit_per_collection=50, include_samples_in_snapshot=True
                )
                inferred = len(
                    infer_foreign_keys(
                        _asa_shapes(snapshot),
                        options=InferenceOptions(sample_overlap=True),
                        sampler=ArangoValueSampler(db),
                    )
                )
            rows.append((label, classes, object_props, inferred))
    finally:
        sys_db = client.db("_system", username=user, password=password)
        for name in (GRAPH_DB, JOINS_DB):
            if sys_db.has_database(name):
                sys_db.delete_database(name)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--arango-url", default="http://localhost:8529")
    parser.add_argument("--arango-user", default="root")
    parser.add_argument("--arango-password", default="openSesame")
    parser.add_argument("--skip-arango", action="store_true")
    parser.add_argument(
        "--arango-only",
        action="store_true",
        help="for running under an ASA-enabled venv",
    )
    args = parser.parse_args()

    if not args.arango_only:
        print(
            "\nRELATIONAL (DuckDB) — identical data, only the declared constraints differ"
        )
        print(
            f"  {'fixture':<20}{'AOE classes':>13}{'AOE relations':>15}{'RSA inferred':>14}"
        )
        for label, classes, props, inferred in run_relational():
            print(f"  {label:<20}{classes:>13}{props:>15}{inferred:>14}")

    if not args.skip_arango:
        print("\nARANGODB — identical model, relationships explicit vs implied")
        print(
            f"  {'fixture':<20}{'AOE classes':>13}{'AOE relations':>15}{'ASA inferred':>14}"
        )
        try:
            for label, classes, props, inferred in run_arango(
                args.arango_url, args.arango_user, args.arango_password
            ):
                shown = "n/a" if inferred is None else str(inferred)
                aoe_c = "n/a" if classes < 0 else str(classes)
                aoe_p = "n/a" if props < 0 else str(props)
                print(f"  {label:<20}{aoe_c:>13}{aoe_p:>15}{shown:>14}")
            print(
                "\n  ('n/a' under ASA means arangodb-schema-analyzer is not importable here — see the docstring.)"
            )
        except Exception as exc:
            print(f"  skipped: {type(exc).__name__}: {exc}")
            print(
                f"  (is ArangoDB reachable at {args.arango_url}? use --skip-arango to omit)"
            )

    print(
        "\nReading it: where relationships are DECLARED the libraries correctly add\n"
        "nothing. Where they are only IMPLIED, AOE emits zero relationships and the\n"
        "libraries recover them all.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
