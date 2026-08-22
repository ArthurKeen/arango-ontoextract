"use client";

import { useEffect, useState, useCallback, useMemo, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { api, ApiError, backendUrl, type PaginatedResponse } from "@/lib/api-client";
import { withBasePath } from "@/lib/base-path";
import type {
  OntologyClass,
  OntologyProperty,
  OntologyEdge,
  OntologyRegistryEntry,
  InstanceGraph,
} from "@/types/curation";
import type { TemporalSnapshot } from "@/types/timeline";
import NodeDetail from "@/components/curation/NodeDetail";
import ProvenancePanel from "@/components/curation/ProvenancePanel";
import EntityHistory from "@/components/timeline/EntityHistory";
import AddClassDialog from "@/components/graph/AddClassDialog";
import AddPropertyDialog from "@/components/graph/AddPropertyDialog";
import EditableLabel from "@/components/graph/EditableLabel";
import ReparentSelect from "@/components/graph/ReparentSelect";
import ThemeToggle from "@/components/ui/ThemeToggle";

const GraphCanvas = dynamic(
  () => import("@/components/graph/GraphCanvas"),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center h-full text-gray-400 animate-pulse">
        Loading graph...
      </div>
    ),
  },
);

const VCRTimeline = dynamic(
  () => import("@/components/timeline/VCRTimeline"),
  { ssr: false },
);

type SidePanel = "detail" | "provenance" | "history";

interface OntologyGraphData {
  classes: OntologyClass[];
  properties: OntologyProperty[];
  edges: OntologyEdge[];
}

export default function OntologyEditorPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-gray-400 animate-pulse">Loading ontology editor...</p>
      </div>
    }>
      <OntologyEditorPageInner />
    </Suspense>
  );
}

function OntologyEditorPageInner() {
  const searchParams = useSearchParams();
  const ontologyId = searchParams.get("ontologyId") || "";

  const [graph, setGraph] = useState<OntologyGraphData | null>(null);
  const [ontologyMeta, setOntologyMeta] = useState<OntologyRegistryEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null);
  const [multiSelected, setMultiSelected] = useState<string[]>([]);
  const [activePanel, setActivePanel] = useState<SidePanel>("detail");
  const [colorMode, setColorMode] = useState<"confidence" | "status">("confidence");
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [snapshotTimestamp, setSnapshotTimestamp] = useState<number | null>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [vcrVisibleKeys, setVcrVisibleKeys] = useState<Set<string> | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [addClassOpen, setAddClassOpen] = useState(false);
  const [addPropertyOpen, setAddPropertyOpen] = useState(false);

  // A-box canvas overlay (FR-18.13). Instances are opt-in and expanded per class
  // so instance volume cannot swamp the T-box layout.
  const [instanceCounts, setInstanceCounts] = useState<Record<string, number>>({});
  const [expandedClassKeys, setExpandedClassKeys] = useState<string[]>([]);
  const [instanceGraph, setInstanceGraph] = useState<InstanceGraph | null>(null);
  const [instancesLoading, setInstancesLoading] = useState(false);
  const [selectedIndividualKey, setSelectedIndividualKey] = useState<string | null>(null);

  const fetchGraph = useCallback(async () => {
    if (!ontologyId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [classesRes, edgesRes, libraryRes] = await Promise.all([
        api.get<{ data: OntologyClass[] }>(
          `/api/v1/ontology/${ontologyId}/classes`,
        ),
        api.get<{ data: OntologyEdge[] }>(
          `/api/v1/ontology/${ontologyId}/edges`,
        ),
        api.get<PaginatedResponse<OntologyRegistryEntry>>(
          "/api/v1/ontology/library",
        ),
      ]);

      const entry = libraryRes.data.find(
        (o) => o._key === ontologyId || o.ontology_id === ontologyId,
      );
      setOntologyMeta(entry ?? null);

      let properties: OntologyProperty[] = [];
      try {
        const propsRes = await api.get<{ data: OntologyProperty[] }>(
          `/api/v1/ontology/${ontologyId}/properties`,
        );
        properties = propsRes.data;
      } catch {
        // properties endpoint may not exist yet — proceed without them
      }

      setGraph({
        classes: classesRes.data,
        properties,
        edges: edgesRes.data,
      });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.body.message
          : "Failed to load ontology graph",
      );
    } finally {
      setLoading(false);
    }
  }, [ontologyId]);

  useEffect(() => {
    fetchGraph();
  }, [fetchGraph]);

  const refreshGraph = useCallback(() => {
    fetchGraph();
  }, [fetchGraph]);

  // --- A-box overlay (FR-18.13) ---

  // Counts only: cheap enough to load with the graph, and it drives the
  // "Instances (N)" affordance without fetching a single individual.
  useEffect(() => {
    if (!ontologyId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<{ counts: Record<string, number> }>(
          `/api/v1/ontology/${ontologyId}/individuals/counts`,
        );
        if (!cancelled) setInstanceCounts(res.counts ?? {});
      } catch {
        // A-box collections may not exist yet — treat as "no instances".
        if (!cancelled) setInstanceCounts({});
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ontologyId]);

  useEffect(() => {
    if (!ontologyId || expandedClassKeys.length === 0) {
      setInstanceGraph(null);
      return;
    }
    let cancelled = false;
    setInstancesLoading(true);
    (async () => {
      try {
        const qs = expandedClassKeys
          .map((k) => `class_keys=${encodeURIComponent(k)}`)
          .join("&");
        const res = await api.get<InstanceGraph>(
          `/api/v1/ontology/${ontologyId}/instance-graph?${qs}`,
        );
        if (!cancelled) setInstanceGraph(res);
      } catch {
        if (!cancelled) setInstanceGraph(null);
      } finally {
        if (!cancelled) setInstancesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ontologyId, expandedClassKeys]);

  const toggleInstances = useCallback((classKey: string) => {
    setExpandedClassKeys((prev) =>
      prev.includes(classKey)
        ? prev.filter((k) => k !== classKey)
        : [...prev, classKey],
    );
  }, []);

  const selectedIndividual = useMemo(
    () =>
      instanceGraph?.individuals.find((i) => i._key === selectedIndividualKey) ?? null,
    [instanceGraph, selectedIndividualKey],
  );

  const selectedNode = useMemo(
    () => graph?.classes.find((c) => c._key === selectedNodeKey) ?? null,
    [graph, selectedNodeKey],
  );

  const selectedEdge = useMemo(
    () => graph?.edges.find((e) => e._key === selectedEdgeKey) ?? null,
    [graph, selectedEdgeKey],
  );

  const handleNodeSelect = useCallback((key: string) => {
    setSelectedNodeKey(key);
    setSelectedEdgeKey(null);
    setActivePanel("detail");
  }, []);

  const handleEdgeSelect = useCallback((key: string) => {
    setSelectedEdgeKey(key);
    setSelectedNodeKey(null);
  }, []);

  const handleSelectionChange = useCallback((keys: string[]) => {
    setMultiSelected(keys);
  }, []);

  const handleDescriptionChange = useCallback(
    (key: string, description: string) => {
      setGraph((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          classes: prev.classes.map((c) =>
            c._key === key ? { ...c, description } : c,
          ),
        };
      });
      api
        .put(`/api/v1/ontology/${ontologyId}/classes/${key}`, { description })
        .catch(() => {});
    },
    [ontologyId],
  );

  // Inline class rename (EditableLabel). Optimistic, with a server round-trip.
  const handleRenameClass = useCallback(
    async (key: string, label: string) => {
      setGraph((prev) =>
        prev
          ? {
              ...prev,
              classes: prev.classes.map((c) => (c._key === key ? { ...c, label } : c)),
            }
          : prev,
      );
      await api.put(`/api/v1/ontology/${ontologyId}/classes/${key}`, { label });
    },
    [ontologyId],
  );

  // Parent-picker data for ReparentSelect: the class list + the selected class's
  // current parent, derived from its live subclass_of edge.
  const availableClasses = useMemo(
    () => (graph?.classes ?? []).map((c) => ({ _key: c._key, label: c.label })),
    [graph],
  );
  const selectedParentKey = useMemo(() => {
    if (!selectedNodeKey || !graph) return undefined;
    const fromId = `ontology_classes/${selectedNodeKey}`;
    const edge = graph.edges.find(
      (e) => e.type === "subclass_of" && e._from === fromId,
    );
    return edge?._to?.split("/").pop();
  }, [selectedNodeKey, graph]);

  const hasData = graph != null && graph.classes.length > 0;

  const handleTimestampChange = useCallback(
    (timestamp: number) => {
      setSnapshotTimestamp(timestamp);
    },
    [],
  );

  const returnToCurrent = useCallback(() => {
    setSnapshotTimestamp(null);
    setVcrVisibleKeys(null);
    fetchGraph();
  }, [fetchGraph]);

  const handleRevert = useCallback(
    (_classKey: string, _versionNumber: number) => {
      fetchGraph();
    },
    [fetchGraph],
  );

  const ontologyName = ontologyMeta?.name ?? ontologyId;
  const ontologyDescription = ontologyMeta?.description ?? "";

  if (!ontologyId && !loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <h1 className="text-xl font-bold mb-2">No Ontology Selected</h1>
          <p className="text-gray-500 mb-4">Please provide an ontologyId parameter.</p>
          <Link href="/library" className="text-blue-600 hover:underline">Back to Library</Link>
        </div>
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      {/* Header / Toolbar */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-[1600px] mx-auto px-6 py-4 flex items-center justify-between">
          <div className="min-w-0">
            <h1 className="text-xl font-bold tracking-tight truncate">
              Ontology Editor
              <span className="text-gray-400 font-normal ml-2">—</span>
              <span className="text-gray-700 font-semibold ml-2 truncate">
                {ontologyName}
              </span>
            </h1>
            {ontologyDescription && (
              <p className="text-sm text-gray-500 truncate">
                {ontologyDescription}
              </p>
            )}
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            {/* Add Class */}
            <button
              disabled={!hasData && !loading}
              onClick={() => setAddClassOpen(true)}
              className="text-xs px-3 py-1.5 bg-blue-600 text-on-accent rounded-lg hover:brightness-90 font-medium disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="add-class-btn"
            >
              + Add Class
            </button>

            {/* Add Property — only enabled when a class is selected */}
            <button
              disabled={!selectedNodeKey}
              onClick={() => setAddPropertyOpen(true)}
              className="text-xs px-3 py-1.5 border border-gray-200 rounded-lg text-gray-600 hover:bg-gray-50 font-medium disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="add-property-btn"
            >
              + Add Property
            </button>

            {/* Color mode toggle */}
            <div className="flex rounded-lg border border-gray-200 overflow-hidden">
              <button
                onClick={() => setColorMode("confidence")}
                disabled={!hasData}
                className={`text-xs px-3 py-1.5 ${colorMode === "confidence" ? "bg-blue-50 text-blue-700 font-medium" : "text-gray-500 hover:bg-gray-50"} disabled:opacity-40 disabled:cursor-not-allowed`}
              >
                Confidence
              </button>
              <button
                onClick={() => setColorMode("status")}
                disabled={!hasData}
                className={`text-xs px-3 py-1.5 border-l border-gray-200 ${colorMode === "status" ? "bg-blue-50 text-blue-700 font-medium" : "text-gray-500 hover:bg-gray-50"} disabled:opacity-40 disabled:cursor-not-allowed`}
              >
                Status
              </button>
            </div>

            {/* VCR Timeline toggle */}
            <button
              onClick={() => setTimelineOpen(!timelineOpen)}
              disabled={!hasData}
              className={`text-xs px-3 py-1.5 border rounded-lg transition-colors ${timelineOpen ? "bg-violet-50 text-violet-700 border-violet-200" : "border-gray-200 text-gray-500 hover:bg-gray-50"} disabled:opacity-40 disabled:cursor-not-allowed`}
            >
              VCR Timeline
            </button>

            {/* Export dropdown */}
            <div className="relative">
              <button
                onClick={() => setExportOpen((v) => !v)}
                onBlur={() => setTimeout(() => setExportOpen(false), 150)}
                disabled={!hasData}
                className="text-xs px-3 py-1.5 border border-gray-200 rounded-lg text-gray-500 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                data-testid="export-btn"
              >
                Export ▾
              </button>
              {exportOpen && (
                <div className="absolute right-0 mt-1 w-40 bg-white border border-gray-200 rounded-lg shadow-lg z-10">
                  {(["turtle", "jsonld", "csv"] as const).map((fmt) => {
                    const label =
                      fmt === "turtle"
                        ? "OWL / Turtle"
                        : fmt === "jsonld"
                          ? "JSON-LD"
                          : "CSV";
                    return (
                      <a
                        key={fmt}
                        href={backendUrl(`/api/v1/ontology/${ontologyId}/export?format=${fmt}`)}
                        target="_blank"
                        rel="noopener noreferrer"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => setExportOpen(false)}
                        className="block px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 first:rounded-t-lg last:rounded-b-lg"
                      >
                        {label}
                      </a>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="flex items-center gap-3">
              <Link
                href={`/workspace?ontologyId=${ontologyId}`}
                className="text-sm font-medium text-indigo-600 hover:text-indigo-800"
              >
                Open in Workspace
              </Link>
              <Link
                href="/library"
                className="text-sm text-gray-500 hover:text-gray-700"
              >
                &larr; Library
              </Link>
              {/* Raw <a> so the trailing slash survives — Next <Link href="/"> drops it. */}
              <a
                href={withBasePath("/")}
                className="text-sm text-gray-500 hover:text-gray-700"
              >
                Home
              </a>
              <ThemeToggle className="ml-1" />

            </div>
          </div>
        </div>
      </header>

      {/* Historical snapshot banner */}
      {snapshotTimestamp && (
        <div className="bg-amber-50 border-b border-amber-200" data-testid="snapshot-banner">
          <div className="max-w-[1600px] mx-auto px-6 py-2 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-amber-800">
              <span className="inline-block h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
              Viewing historical snapshot at{" "}
              <span className="font-mono font-medium">
                {new Date(snapshotTimestamp * 1000).toLocaleString()}
              </span>
              {snapshotLoading && (
                <span className="text-amber-500 animate-pulse ml-2">Loading...</span>
              )}
            </div>
            <button
              onClick={returnToCurrent}
              className="text-xs px-3 py-1.5 bg-amber-600 text-on-accent rounded-lg hover:brightness-90"
              data-testid="return-to-current"
            >
              Return to current
            </button>
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="max-w-[1600px] mx-auto flex flex-col">
        <div className="flex flex-1 min-h-[calc(100vh-73px)]">
          {/* Graph viewport (~70%) */}
          <div className="flex-[7] flex flex-col">
            {loading && (
              <div className="flex-1 flex items-center justify-center">
                <p className="text-gray-400 animate-pulse">
                  Loading ontology graph...
                </p>
              </div>
            )}

            {error && (
              <div className="flex-1 flex items-center justify-center p-8">
                <div className="text-center">
                  <p className="text-red-500 text-lg mb-2">{error}</p>
                  <button
                    onClick={refreshGraph}
                    className="text-sm px-4 py-2 bg-blue-600 text-on-accent rounded-lg hover:brightness-90"
                  >
                    Retry
                  </button>
                </div>
              </div>
            )}

            {!loading && !error && !hasData && (
              <div className="flex-1 flex items-center justify-center p-8">
                <div className="text-center max-w-md">
                  <div className="text-4xl text-gray-300 mb-4">{"\u{1F4D6}"}</div>
                  <h2 className="text-lg font-semibold text-gray-700 mb-2">
                    This ontology has no classes yet
                  </h2>
                  <p className="text-sm text-gray-500 mb-4">
                    Add your first class to start building the ontology graph.
                  </p>
                  <div className="flex gap-3 justify-center">
                    <button
                      onClick={() => {
                        /* AddClassDialog will be wired here */
                      }}
                      className="text-sm px-4 py-2 bg-blue-600 text-on-accent rounded-lg hover:brightness-90"
                    >
                      Add First Class
                    </button>
                    <Link
                      href="/library"
                      className="text-sm px-4 py-2 border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50"
                    >
                      Back to Library
                    </Link>
                  </div>
                </div>
              </div>
            )}

            {!loading && !error && hasData && (
              <div className="flex-1 bg-white m-4 rounded-xl border border-gray-200 shadow-sm overflow-hidden relative">
                <GraphCanvas
                  classes={vcrVisibleKeys ? graph.classes.filter((c) => vcrVisibleKeys.has(c._key)) : graph.classes}
                  properties={graph.properties}
                  edges={vcrVisibleKeys ? graph.edges.filter((e) => {
                    const fromKey = e._from.split("/").pop() ?? "";
                    const toKey = e._to.split("/").pop() ?? "";
                    return vcrVisibleKeys.has(fromKey) && vcrVisibleKeys.has(toKey);
                  }) : graph.edges}
                  selectedNodes={
                    selectedNodeKey ? [selectedNodeKey] : multiSelected
                  }
                  onNodeSelect={handleNodeSelect}
                  onEdgeSelect={handleEdgeSelect}
                  onSelectionChange={handleSelectionChange}
                  colorMode={colorMode}
                  individuals={instanceGraph?.individuals ?? []}
                  rdfTypeEdges={instanceGraph?.rdf_type_edges ?? []}
                  assertions={instanceGraph?.assertions ?? []}
                  onIndividualSelect={setSelectedIndividualKey}
                />

                {/* A-box overlay status (FR-18.13) */}
                {expandedClassKeys.length > 0 && (
                  <div
                    className="absolute top-3 left-3 z-10 max-w-[420px] rounded-lg bg-amber-50/95 border border-amber-300 px-3 py-2 text-xs text-amber-900 shadow-sm space-y-1"
                    data-testid="abox-overlay-status"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">
                        Instances shown for {expandedClassKeys.length}{" "}
                        {expandedClassKeys.length === 1 ? "class" : "classes"}
                      </span>
                      {instancesLoading && (
                        <span className="animate-pulse text-amber-700">loading…</span>
                      )}
                      <button
                        onClick={() => {
                          setExpandedClassKeys([]);
                          setSelectedIndividualKey(null);
                        }}
                        className="ml-auto underline hover:no-underline"
                        data-testid="clear-instances"
                      >
                        Clear
                      </button>
                    </div>
                    {(instanceGraph?.truncated?.length ?? 0) > 0 && (
                      <p data-testid="abox-truncated" className="text-amber-800">
                        Capped at the per-class limit for:{" "}
                        {instanceGraph?.truncated.join(", ")}. Not all instances are
                        shown.
                      </p>
                    )}
                    {selectedIndividual && (
                      <p data-testid="abox-selected-individual">
                        Selected instance: <strong>{selectedIndividual.label}</strong>
                        {Array.isArray(selectedIndividual.provenance) && (
                          <>
                            {" "}
                            · {selectedIndividual.provenance.length} source span
                            {selectedIndividual.provenance.length === 1 ? "" : "s"}
                          </>
                        )}
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* VCR Timeline */}
            {timelineOpen && hasData && (
              <div className="mx-4 mb-4">
                <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
                  <VCRTimeline
                    ontologyId={ontologyId}
                    onTimestampChange={handleTimestampChange}
                    onVisibleEntitiesChange={setVcrVisibleKeys}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Side panel (~30%) */}
          <aside className="flex-[3] bg-white border-l border-gray-200 overflow-y-auto max-lg:hidden">
            <div className="p-4 space-y-4">
              {activePanel === "detail" && selectedNode && (
                <div className="space-y-3">
                  <div className="space-y-2 pb-2 border-b border-gray-100">
                    <EditableLabel
                      value={selectedNode.label}
                      onSave={(label) => handleRenameClass(selectedNode._key, label)}
                      className="text-base font-semibold text-gray-900"
                    />
                    <ReparentSelect
                      ontologyId={ontologyId}
                      classKey={selectedNode._key}
                      currentParentKey={selectedParentKey}
                      availableClasses={availableClasses}
                      onReparented={refreshGraph}
                    />
                    {/* A-box instance expansion (FR-18.13) */}
                    {(instanceCounts[selectedNode._key] ?? 0) > 0 ? (
                      <button
                        onClick={() => toggleInstances(selectedNode._key)}
                        className={`w-full text-xs px-2 py-1.5 rounded-lg border transition-colors ${
                          expandedClassKeys.includes(selectedNode._key)
                            ? "bg-amber-100 border-amber-400 text-amber-900"
                            : "bg-white border-gray-300 text-gray-600 hover:bg-amber-50"
                        }`}
                        data-testid="toggle-instances"
                      >
                        {expandedClassKeys.includes(selectedNode._key)
                          ? `Hide instances (${instanceCounts[selectedNode._key]})`
                          : `Show instances (${instanceCounts[selectedNode._key]})`}
                      </button>
                    ) : (
                      <p
                        className="text-[11px] text-gray-400"
                        data-testid="no-instances"
                      >
                        No instances extracted for this class.
                      </p>
                    )}
                  </div>
                  <NodeDetail
                    node={selectedNode}
                    onDescriptionChange={handleDescriptionChange}
                    onShowProvenance={() => setActivePanel("provenance")}
                    onShowHistory={() => setActivePanel("history")}
                  />
                </div>
              )}

              {activePanel === "detail" && selectedEdge && !selectedNode && (
                <div className="space-y-3" data-testid="edge-detail">
                  <h3 className="text-base font-semibold text-gray-900">
                    Edge: {selectedEdge.label || selectedEdge.type}
                  </h3>
                  <div className="space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span className="text-gray-500">Type</span>
                      <span className="text-gray-700 font-mono">{selectedEdge.type}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">From</span>
                      <span className="text-gray-700 font-mono truncate ml-2">
                        {selectedEdge._from.split("/").pop()}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">To</span>
                      <span className="text-gray-700 font-mono truncate ml-2">
                        {selectedEdge._to.split("/").pop()}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {activePanel === "detail" && !selectedNode && !selectedEdge && (
                <div className="py-12 text-center">
                  <p className="text-gray-400 text-sm">
                    Select a node or edge to view details
                  </p>
                </div>
              )}

              {activePanel === "provenance" && selectedNode && (
                <ProvenancePanel
                  entityKey={selectedNode._key}
                  entityLabel={selectedNode.label}
                  onClose={() => setActivePanel("detail")}
                />
              )}

              {activePanel === "history" && selectedNode && (
                <EntityHistory
                  classKey={selectedNode._key}
                  onClose={() => setActivePanel("detail")}
                  onRevert={handleRevert}
                />
              )}

              {activePanel === "history" && !selectedNode && (
                <div className="py-12 text-center">
                  <p className="text-gray-400 text-sm">
                    Select a node to view its version history
                  </p>
                </div>
              )}
            </div>
          </aside>
        </div>
      </div>

      {/* Mobile side panel toggle */}
      {selectedNode && (
        <div className="lg:hidden fixed bottom-4 right-4 z-20">
          <button
            onClick={() => setActivePanel("detail")}
            className="bg-blue-600 text-on-accent px-4 py-2 rounded-full shadow-lg text-sm font-medium hover:brightness-90"
          >
            View: {selectedNode.label}
          </button>
        </div>
      )}
      {addClassOpen && (
        <AddClassDialog
          ontologyId={ontologyId}
          existingClasses={(graph?.classes ?? []).map((c) => ({ _key: c._key, label: c.label }))}
          onCreated={() => { setAddClassOpen(false); fetchGraph(); }}
          onClose={() => setAddClassOpen(false)}
        />
      )}

      {addPropertyOpen && selectedNode && (
        <AddPropertyDialog
          ontologyId={ontologyId}
          domainClassKey={selectedNode._key}
          domainClassLabel={selectedNode.label}
          onCreated={() => { setAddPropertyOpen(false); fetchGraph(); }}
          onClose={() => setAddPropertyOpen(false)}
        />
      )}
    </main>
  );
}
