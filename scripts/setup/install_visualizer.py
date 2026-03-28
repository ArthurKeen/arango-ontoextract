"""Idempotent installer for ArangoDB Graph Visualizer customization assets.

Installs themes, canvas actions, saved queries, graph visualizer queries,
viewpoints, and viewpoint-action/query links for ontology graphs in the
AOE platform.

Usage:
    python scripts/setup/install_visualizer.py          # uses app.config.settings
    python scripts/setup/install_visualizer.py --help   # standalone CLI args

Importable:
    from scripts.setup.install_visualizer import install_all
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from arango import ArangoClient
from arango.database import StandardDatabase

log = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "visualizer"
THEME_PATH = ASSETS_DIR / "themes" / "ontology_theme.json"
ACTIONS_PATH = ASSETS_DIR / "actions" / "ontology_actions.json"
QUERIES_PATH = ASSETS_DIR / "queries" / "ontology_queries.json"

NEVER_EXPIRES = 9223372036854775807

SYSTEM_COLLECTIONS = [
    "_graphThemeStore",
    "_canvasActions",
    "_editor_saved_queries",
    "_queries",
    "_viewpoints",
]

SYSTEM_EDGE_COLLECTIONS = [
    "_viewpointActions",
    "_viewpointQueries",
]

DEFAULT_GRAPH_NAME = "domain_ontology"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_collection(
    db: StandardDatabase,
    name: str,
    *,
    edge: bool = False,
) -> None:
    """Create a collection if it doesn't exist. System-prefixed collections
    get ``system=True`` so ArangoDB accepts the ``_`` prefix."""
    if db.has_collection(name):
        return
    is_system = name.startswith("_")
    db.create_collection(name, edge=edge, system=is_system)
    log.info("created collection %s (edge=%s, system=%s)", name, edge, is_system)


def ensure_all_collections(db: StandardDatabase) -> None:
    for name in SYSTEM_COLLECTIONS:
        ensure_collection(db, name)
    for name in SYSTEM_EDGE_COLLECTIONS:
        ensure_collection(db, name, edge=True)


def _upsert_by_key(
    db: StandardDatabase,
    collection_name: str,
    doc: dict,
) -> str:
    """Insert or replace a document keyed by ``_key``. Returns the ``_id``."""
    col = db.collection(collection_name)
    key = doc["_key"]
    now = _now_iso()
    doc.setdefault("createdAt", now)
    doc["updatedAt"] = now
    if col.has(key):
        col.replace(doc, check_rev=False)
        log.debug("replaced %s/%s", collection_name, key)
    else:
        col.insert(doc)
        log.debug("inserted %s/%s", collection_name, key)
    return f"{collection_name}/{key}"


def _ensure_edge(
    db: StandardDatabase,
    edge_collection: str,
    from_id: str,
    to_id: str,
) -> None:
    """Insert an edge if one with the same _from/_to doesn't already exist."""
    col = db.collection(edge_collection)
    existing = list(col.find({"_from": from_id, "_to": to_id}, limit=1))
    if existing:
        log.debug("edge %s -> %s already exists in %s", from_id, to_id, edge_collection)
        return
    col.insert({"_from": from_id, "_to": to_id, "createdAt": _now_iso()})
    log.debug("created edge %s -> %s in %s", from_id, to_id, edge_collection)


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


def ensure_visualizer_shape(theme: dict) -> None:
    """Add required defaults for any missing fields in theme configs."""
    for node_cfg in theme.get("nodeConfigMap", {}).values():
        node_cfg.setdefault("rules", [])
        node_cfg.setdefault("hoverInfoAttributes", [])
    for edge_cfg in theme.get("edgeConfigMap", {}).values():
        edge_cfg.setdefault("rules", [])
        edge_cfg.setdefault("hoverInfoAttributes", [])
        edge_cfg.setdefault(
            "arrowStyle",
            {"sourceArrowShape": "none", "targetArrowShape": "triangle"},
        )
        edge_cfg.setdefault("labelStyle", {"color": "#1d2531"})


def prune_theme(
    theme_raw: dict,
    vertex_colls: set[str],
    edge_colls: set[str],
) -> dict:
    """Return a copy of the theme with configs pruned to only collections
    that exist in the target graph."""
    theme = copy.deepcopy(theme_raw)
    if "nodeConfigMap" in theme:
        theme["nodeConfigMap"] = {
            k: v for k, v in theme["nodeConfigMap"].items() if k in vertex_colls
        }
    if "edgeConfigMap" in theme:
        theme["edgeConfigMap"] = {
            k: v for k, v in theme["edgeConfigMap"].items() if k in edge_colls
        }
    return theme


def _load_theme(graph_name: str) -> dict:
    raw = json.loads(THEME_PATH.read_text(encoding="utf-8"))
    raw["graphId"] = graph_name
    raw["_key"] = f"aoe_ontology_{graph_name}"
    ensure_visualizer_shape(raw)
    return raw


def _default_theme(graph_name: str) -> dict:
    """Plain default theme so users can switch back after DB recreation."""
    return {
        "_key": f"aoe_default_{graph_name}",
        "name": "Default",
        "graphId": graph_name,
        "isDefault": False,
        "nodeConfigMap": {},
        "edgeConfigMap": {},
    }


def install_themes(db: StandardDatabase, graph_name: str) -> None:
    """Install the ontology theme and a fallback default theme."""
    ensure_collection(db, "_graphThemeStore")
    theme = _load_theme(graph_name)
    _upsert_by_key(db, "_graphThemeStore", theme)
    _upsert_by_key(db, "_graphThemeStore", _default_theme(graph_name))
    log.info(
        "installed themes for graph %s (%d node types, %d edge types)",
        graph_name,
        len(theme.get("nodeConfigMap", {})),
        len(theme.get("edgeConfigMap", {})),
    )


def install_pruned_theme(
    db: StandardDatabase,
    graph_name: str,
) -> dict:
    """Install a theme pruned to the collections actually present in the graph.
    Returns the pruned theme dict."""
    theme_raw = _load_theme(graph_name)

    vertex_colls: set[str] = set()
    edge_colls: set[str] = set()

    if db.has_graph(graph_name):
        graph = db.graph(graph_name)
        for edef in graph.edge_definitions():
            edge_colls.add(edef["edge_collection"])
            vertex_colls.update(edef["from_vertex_collections"])
            vertex_colls.update(edef["to_vertex_collections"])

    pruned = prune_theme(theme_raw, vertex_colls, edge_colls)
    pruned["_key"] = theme_raw["_key"]
    pruned["graphId"] = graph_name
    pruned["name"] = theme_raw["name"]
    pruned["isDefault"] = True
    ensure_visualizer_shape(pruned)

    ensure_collection(db, "_graphThemeStore")
    _upsert_by_key(db, "_graphThemeStore", pruned)
    _upsert_by_key(db, "_graphThemeStore", _default_theme(graph_name))
    log.info(
        "installed pruned theme for %s (%d node types, %d edge types)",
        graph_name,
        len(pruned.get("nodeConfigMap", {})),
        len(pruned.get("edgeConfigMap", {})),
    )
    return pruned


# ---------------------------------------------------------------------------
# Canvas Actions
# ---------------------------------------------------------------------------


def _load_actions(graph_name: str) -> list[dict]:
    actions = json.loads(ACTIONS_PATH.read_text(encoding="utf-8"))
    for action in actions:
        action["graphId"] = graph_name
    return actions


def install_canvas_actions(db: StandardDatabase, graph_name: str) -> list[str]:
    """Install canvas actions. Returns list of _id values."""
    ensure_collection(db, "_canvasActions")
    actions = _load_actions(graph_name)
    ids = []
    for action in actions:
        doc_id = _upsert_by_key(db, "_canvasActions", action)
        ids.append(doc_id)
    log.info("installed %d canvas actions for graph %s", len(ids), graph_name)
    return ids


# ---------------------------------------------------------------------------
# Saved Queries (global query editor: _editor_saved_queries)
# ---------------------------------------------------------------------------


def _load_queries(db_name: str) -> list[dict]:
    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    for q in queries:
        q["databaseName"] = db_name
    return queries


def install_saved_queries(db: StandardDatabase, graph_name: str) -> list[str]:
    """Install saved queries into _editor_saved_queries (global query editor)
    and _queries (Graph Visualizer Queries panel). Returns list of _id values
    from _editor_saved_queries."""
    ensure_collection(db, "_editor_saved_queries")
    ensure_collection(db, "_queries")
    queries = _load_queries(db.name)
    editor_ids = []
    for q in queries:
        doc_id = _upsert_by_key(db, "_editor_saved_queries", q)
        editor_ids.append(doc_id)

        viz_query = {
            "_key": q["_key"],
            "name": q["name"],
            "description": q.get("description", ""),
            "queryText": q["content"],
            "graphId": graph_name,
            "bindVariables": q.get("bindVariables", {}),
        }
        _upsert_by_key(db, "_queries", viz_query)

    log.info("installed %d saved queries for graph %s", len(editor_ids), graph_name)
    return editor_ids


# ---------------------------------------------------------------------------
# Viewpoints
# ---------------------------------------------------------------------------


def ensure_default_viewpoint(db: StandardDatabase, graph_name: str) -> str:
    """Create a 'Default' viewpoint for the given graph if it doesn't exist.
    Returns the viewpoint ``_id``."""
    ensure_collection(db, "_viewpoints")
    col = db.collection("_viewpoints")
    existing = list(col.find({"graphId": graph_name, "name": "Default"}, limit=1))
    if existing:
        vp_id = existing[0]["_id"]
        log.debug("viewpoint for %s already exists: %s", graph_name, vp_id)
        return vp_id

    now = _now_iso()
    result = col.insert({
        "graphId": graph_name,
        "name": "Default",
        "description": f"Default viewpoint for {graph_name}",
        "createdAt": now,
        "updatedAt": now,
    })
    vp_id = result["_id"]
    log.info("created viewpoint for %s: %s", graph_name, vp_id)
    return vp_id


def link_actions_to_viewpoint(
    db: StandardDatabase,
    viewpoint_id: str,
    action_ids: list[str],
) -> None:
    """Create _viewpointActions edges from the viewpoint to each canvas action."""
    ensure_collection(db, "_viewpointActions", edge=True)
    for action_id in action_ids:
        _ensure_edge(db, "_viewpointActions", viewpoint_id, action_id)
    log.info("linked %d actions to viewpoint %s", len(action_ids), viewpoint_id)


def link_queries_to_viewpoint(
    db: StandardDatabase,
    viewpoint_id: str,
    query_keys: list[str],
) -> None:
    """Create _viewpointQueries edges from the viewpoint to each _queries doc."""
    ensure_collection(db, "_viewpointQueries", edge=True)
    for key in query_keys:
        query_id = f"_queries/{key}"
        _ensure_edge(db, "_viewpointQueries", viewpoint_id, query_id)
    log.info("linked %d queries to viewpoint %s", len(query_keys), viewpoint_id)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def install_all(
    db: StandardDatabase,
    graph_name: str = DEFAULT_GRAPH_NAME,
    *,
    prune: bool = False,
) -> dict:
    """Install all visualizer assets for the given graph. Returns a summary dict.

    Args:
        db: ArangoDB database handle.
        graph_name: Target graph name (default: ``domain_ontology``).
        prune: If True, prune theme to collections that exist in the graph.
    """
    log.info("installing visualizer assets for graph %s (prune=%s)", graph_name, prune)

    ensure_all_collections(db)

    if prune:
        theme = install_pruned_theme(db, graph_name)
    else:
        install_themes(db, graph_name)
        theme = _load_theme(graph_name)

    action_ids = install_canvas_actions(db, graph_name)
    install_saved_queries(db, graph_name)

    vp_id = ensure_default_viewpoint(db, graph_name)
    link_actions_to_viewpoint(db, vp_id, action_ids)

    query_keys = [q["_key"] for q in _load_queries(db.name)]
    link_queries_to_viewpoint(db, vp_id, query_keys)

    summary = {
        "graph_name": graph_name,
        "theme_node_types": len(theme.get("nodeConfigMap", {})),
        "theme_edge_types": len(theme.get("edgeConfigMap", {})),
        "canvas_actions": len(action_ids),
        "saved_queries": len(query_keys),
        "viewpoint_id": vp_id,
    }
    log.info("visualizer install complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _connect_from_settings() -> StandardDatabase:
    """Connect using app.config.settings (for use within the AOE project)."""
    backend_root = Path(__file__).resolve().parent.parent.parent / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from app.db.client import get_db

    return get_db()


def _connect_standalone(args: argparse.Namespace) -> StandardDatabase:
    """Connect using CLI arguments."""
    client = ArangoClient(hosts=args.host)
    sys_db = client.db(
        "_system",
        username=args.user,
        password=args.password,
    )
    if args.db not in sys_db.databases():
        sys_db.create_database(args.db)
    return client.db(args.db, username=args.user, password=args.password)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install ArangoDB Graph Visualizer customizations for AOE.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="ArangoDB host URL (default: use app.config.settings)",
    )
    parser.add_argument("--db", default=None, help="Target database name")
    parser.add_argument("--user", default="root", help="ArangoDB username")
    parser.add_argument("--password", default="", help="ArangoDB password")
    parser.add_argument(
        "--graph",
        default=DEFAULT_GRAPH_NAME,
        help=f"Target graph name (default: {DEFAULT_GRAPH_NAME})",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Prune theme to collections present in the graph",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    if args.host:
        db = _connect_standalone(args)
    else:
        db = _connect_from_settings()

    summary = install_all(db, graph_name=args.graph, prune=args.prune)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
