"use client";

import { useMemo, useCallback, useState } from "react";
import ReactFlow, {
  type Node,
  type Edge,
  type NodeProps,
  type OnSelectionChangeParams,
  Position,
  Handle,
  Background,
  BackgroundVariant,
  MiniMap,
  Controls,
  MarkerType,
} from "reactflow";
import "reactflow/dist/style.css";
import type {
  OntologyClass,
  OntologyProperty,
  OntologyEdge,
  CurationStatus,
} from "@/types/curation";

// --- Confidence-based color helpers ---

function confidenceColor(confidence: number): string {
  if (confidence >= 0.8) return "border-green-400 bg-green-50";
  if (confidence >= 0.5) return "border-yellow-400 bg-yellow-50";
  return "border-red-400 bg-red-50";
}

function confidenceDotColor(confidence: number): string {
  if (confidence >= 0.8) return "bg-green-500";
  if (confidence >= 0.5) return "bg-yellow-500";
  return "bg-red-500";
}

const STATUS_BORDER: Record<CurationStatus, string> = {
  pending: "border-gray-300 bg-white",
  approved: "border-green-400 bg-green-50",
  rejected: "border-red-400 bg-red-50",
};

// --- Custom Node ---

export interface OntologyNodeData {
  label: string;
  uri: string;
  rdfType: string;
  confidence: number;
  status: CurationStatus;
  classKey: string;
  description: string;
  colorMode: "confidence" | "status";
}

function OntologyNode({ data, selected }: NodeProps<OntologyNodeData>) {
  const { label, confidence, status, rdfType, colorMode } = data;
  const colorClass =
    colorMode === "confidence" ? confidenceColor(confidence) : STATUS_BORDER[status];
  const borderWidth = confidence < 0.5 ? "border-dashed" : "border-solid";
  const nodeSize = Math.max(160, 160 + (confidence - 0.5) * 80);

  return (
    <div
      className={`rounded-lg border-2 ${borderWidth} px-4 py-3 shadow-sm transition-all ${colorClass} ${selected ? "ring-2 ring-blue-500 ring-offset-1" : ""}`}
      style={{ minWidth: nodeSize }}
      data-testid={`graph-node-${data.classKey}`}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-gray-300 !w-2 !h-2"
      />
      <div className="flex items-center gap-2 mb-1">
        <span
          className={`inline-block h-2 w-2 rounded-full ${confidenceDotColor(confidence)}`}
          title={`Confidence: ${(confidence * 100).toFixed(0)}%`}
        />
        <span className="text-sm font-semibold text-gray-800 truncate">
          {label}
        </span>
      </div>
      <div className="text-xs text-gray-500 truncate">{rdfType}</div>
      <div className="mt-1 flex items-center gap-1.5">
        <span className="text-xs text-gray-400">
          {(confidence * 100).toFixed(0)}%
        </span>
        <div className="flex-1 h-1 bg-gray-200 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${confidence >= 0.8 ? "bg-green-500" : confidence >= 0.5 ? "bg-yellow-500" : "bg-red-500"}`}
            style={{ width: `${confidence * 100}%` }}
          />
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-gray-300 !w-2 !h-2"
      />
    </div>
  );
}

const nodeTypes = { ontologyNode: OntologyNode };

// --- Edge label config ---

const EDGE_COLORS: Record<string, string> = {
  subclass_of: "#6366f1",
  equivalent_class: "#8b5cf6",
  has_property: "#0891b2",
  extends_domain: "#d97706",
  related_to: "#64748b",
  extracted_from: "#059669",
  imports: "#e11d48",
};

// --- Layout: simple hierarchical using dagre-like positioning ---

function computeLayout(
  classes: OntologyClass[],
  edges: OntologyEdge[],
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const children = new Map<string, string[]>();
  const parents = new Set<string>();
  const allKeys = new Set(classes.map((c) => c._key));

  for (const edge of edges) {
    const fromKey = edge._from.split("/").pop() ?? edge._from;
    const toKey = edge._to.split("/").pop() ?? edge._to;
    if (!children.has(fromKey)) children.set(fromKey, []);
    children.get(fromKey)!.push(toKey);
    parents.add(toKey);
  }

  const roots = classes.filter((c) => !parents.has(c._key));
  if (roots.length === 0 && classes.length > 0) {
    roots.push(classes[0]);
  }

  const COL_WIDTH = 280;
  const ROW_HEIGHT = 120;
  let currentX = 0;

  function placeSubtree(key: string, depth: number, visited: Set<string>) {
    if (visited.has(key) || !allKeys.has(key)) return;
    visited.add(key);
    positions.set(key, { x: currentX, y: depth * ROW_HEIGHT });
    const kids = children.get(key) ?? [];
    for (const kid of kids) {
      currentX += COL_WIDTH;
      placeSubtree(kid, depth + 1, visited);
    }
  }

  const visited = new Set<string>();
  for (const root of roots) {
    placeSubtree(root._key, 0, visited);
    currentX += COL_WIDTH;
  }

  for (const cls of classes) {
    if (!positions.has(cls._key)) {
      positions.set(cls._key, { x: currentX, y: 0 });
      currentX += COL_WIDTH;
    }
  }

  return positions;
}

// --- Props ---

export interface GraphCanvasProps {
  classes: OntologyClass[];
  properties: OntologyProperty[];
  edges: OntologyEdge[];
  selectedNodes?: string[];
  onNodeSelect?: (classKey: string) => void;
  onEdgeSelect?: (edgeKey: string) => void;
  onSelectionChange?: (selectedKeys: string[]) => void;
  colorMode?: "confidence" | "status";
  className?: string;
}

export default function GraphCanvas({
  classes,
  properties,
  edges,
  selectedNodes = [],
  onNodeSelect,
  onEdgeSelect,
  onSelectionChange,
  colorMode = "confidence",
  className = "",
}: GraphCanvasProps) {
  const [internalSelected, setInternalSelected] = useState<string[]>([]);
  const effectiveSelected = selectedNodes.length > 0 ? selectedNodes : internalSelected;

  const positions = useMemo(
    () => computeLayout(classes, edges),
    [classes, edges],
  );

  const { nodes, flowEdges } = useMemo(() => {
    const flowNodes: Node<OntologyNodeData>[] = classes.map((cls) => {
      const pos = positions.get(cls._key) ?? { x: 0, y: 0 };
      return {
        id: cls._key,
        type: "ontologyNode",
        position: pos,
        selected: effectiveSelected.includes(cls._key),
        data: {
          label: cls.label,
          uri: cls.uri,
          rdfType: cls.rdf_type,
          confidence: cls.confidence,
          status: cls.status,
          classKey: cls._key,
          description: cls.description,
          colorMode,
        },
      };
    });

    const fe: Edge[] = edges.map((edge) => {
      const fromKey = edge._from.split("/").pop() ?? edge._from;
      const toKey = edge._to.split("/").pop() ?? edge._to;
      return {
        id: edge._key,
        source: fromKey,
        target: toKey,
        label: edge.label || edge.type,
        type: "default",
        markerEnd: { type: MarkerType.ArrowClosed },
        style: {
          stroke: EDGE_COLORS[edge.type] ?? "#94a3b8",
          strokeWidth: 2,
        },
        labelStyle: {
          fill: "#64748b",
          fontSize: 11,
          fontWeight: 500,
        },
        labelBgStyle: {
          fill: "#f8fafc",
          fillOpacity: 0.9,
        },
        labelBgPadding: [4, 2] as [number, number],
        data: { edgeKey: edge._key },
      };
    });

    return { nodes: flowNodes, flowEdges: fe };
  }, [classes, edges, positions, effectiveSelected, colorMode]);

  const onInit = useCallback((instance: { fitView: () => void }) => {
    instance.fitView();
  }, []);

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeSelect?.(node.id);
    },
    [onNodeSelect],
  );

  const handleEdgeClick = useCallback(
    (_: React.MouseEvent, edge: Edge) => {
      onEdgeSelect?.(edge.id);
    },
    [onEdgeSelect],
  );

  const handleSelectionChange = useCallback(
    (params: OnSelectionChangeParams) => {
      const keys = params.nodes.map((n) => n.id);
      setInternalSelected(keys);
      onSelectionChange?.(keys);
    },
    [onSelectionChange],
  );

  if (classes.length === 0) {
    return (
      <div
        className={`flex items-center justify-center h-full text-gray-400 ${className}`}
        data-testid="graph-empty"
      >
        <div className="text-center">
          <p className="text-lg">No ontology data available</p>
          <p className="text-sm mt-1">
            The staging graph is empty or still loading.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`w-full h-full min-h-[500px] ${className}`}
      data-testid="graph-canvas"
    >
      <ReactFlow
        nodes={nodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onInit={onInit}
        onNodeClick={handleNodeClick}
        onEdgeClick={handleEdgeClick}
        onSelectionChange={handleSelectionChange}
        fitView
        multiSelectionKeyCode="Shift"
        selectionOnDrag
        selectNodesOnDrag
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
        <Controls
          showInteractive={false}
          className="!bg-white !border-gray-200 !shadow-sm"
        />
        <MiniMap
          nodeColor={(node) => {
            const conf = (node.data as OntologyNodeData)?.confidence ?? 0.5;
            if (conf >= 0.8) return "#22c55e";
            if (conf >= 0.5) return "#eab308";
            return "#ef4444";
          }}
          className="!bg-gray-50 !border-gray-200"
        />
      </ReactFlow>
    </div>
  );
}
