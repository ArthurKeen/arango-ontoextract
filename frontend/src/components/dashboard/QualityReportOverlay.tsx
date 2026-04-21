"use client";

import { useState } from "react";
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import {
  PER_ONTOLOGY_QUALITY_DIMENSIONS,
  healthBgColor,
  healthColor,
  scoreBgColor,
  scoreColor,
  type PerOntologyQualityApiShape,
} from "@/lib/perOntologyQualityDimensions";

interface Props {
  name: string;
  data: PerOntologyQualityApiShape;
  onClose: () => void;
}

interface RadarDatum {
  dimension: string;
  value: number;
  available: boolean;
}

const SCHEMA_METRIC_LABELS: Record<string, string> = {
  relationship_richness: "Relationship Richness",
  attribute_richness: "Attribute Richness",
  inheritance_richness: "Inheritance Richness",
  max_depth: "Max Depth",
  annotation_completeness: "Annotation Completeness",
  relationship_diversity: "Relationship Types",
  avg_connectivity_degree: "Avg Degree",
  uri_consistency: "URI Consistency",
};

function formatSchemaValue(key: string, v: number): string {
  if (
    key === "relationship_richness" ||
    key === "annotation_completeness" ||
    key === "uri_consistency"
  )
    return `${(v * 100).toFixed(0)}%`;
  if (key === "max_depth") return `${Math.round(v)} levels`;
  if (key === "attribute_richness") return `${v.toFixed(1)} props/class`;
  if (key === "inheritance_richness") return `${v.toFixed(1)} sub/parent`;
  if (key === "relationship_diversity") return `${v} distinct`;
  if (key === "avg_connectivity_degree") return `${v.toFixed(1)} edges/class`;
  return v.toFixed(4);
}

export default function QualityReportOverlay({ name, data, onClose }: Props) {
  const [schemaExpanded, setSchemaExpanded] = useState(false);

  const radarData: RadarDatum[] = PER_ONTOLOGY_QUALITY_DIMENSIONS.map(
    (dim) => {
      const raw = dim.compute(data);
      return {
        dimension: dim.label,
        value: raw != null ? Math.round(raw * 100) / 100 : 0,
        available: raw != null,
      };
    },
  );

  const schema = data.schema_metrics;

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="relative bg-white rounded-2xl shadow-2xl w-[90vw] max-w-[900px] max-h-[90vh] overflow-y-auto p-8">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-700 text-2xl leading-none"
          aria-label="Close"
        >
          ×
        </button>

        <div className="space-y-8">
          {data.health_score != null && (
            <div className="flex justify-center">
              <div
                className={`rounded-2xl border-2 px-10 py-6 text-center shadow-sm ${healthBgColor(data.health_score)}`}
              >
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  Health Score — {name}
                </p>
                <p
                  className={`mt-2 text-5xl font-extrabold ${healthColor(data.health_score)}`}
                >
                  {data.health_score}
                </p>
                <p className="text-sm text-gray-500 mt-1">out of 100</p>
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm flex items-center justify-center">
              <ResponsiveContainer width="100%" height={380}>
                <RadarChart
                  data={radarData}
                  cx="50%"
                  cy="50%"
                  outerRadius="70%"
                >
                  <PolarGrid stroke="#e5e7eb" />
                  <PolarAngleAxis
                    dataKey="dimension"
                    tick={{ fontSize: 12, fill: "#4b5563" }}
                  />
                  <PolarRadiusAxis
                    angle={90}
                    domain={[0, 5]}
                    tickCount={6}
                    tick={{ fontSize: 10, fill: "#9ca3af" }}
                  />
                  <Radar
                    name="Quality"
                    dataKey="value"
                    stroke="#2563eb"
                    fill="#3b82f6"
                    fillOpacity={0.3}
                    strokeWidth={2}
                  />
                  <Tooltip
                    formatter={(val) => `${Number(val).toFixed(2)} / 5`}
                    labelStyle={{ fontWeight: 600 }}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 content-start">
              {PER_ONTOLOGY_QUALITY_DIMENSIONS.map((dim) => {
                const raw = dim.compute(data);
                const available = raw != null;
                const score = raw ?? 0;
                return (
                  <div
                    key={dim.key}
                    className={`rounded-xl border p-4 shadow-sm ${
                      available
                        ? scoreBgColor(score)
                        : "bg-gray-50 border-gray-200"
                    }`}
                  >
                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                      {dim.label}
                    </p>
                    <p
                      className={`mt-1 text-2xl font-bold ${
                        available ? scoreColor(score) : "text-gray-300"
                      }`}
                    >
                      {available ? score.toFixed(1) : "—"}{" "}
                      <span className="text-sm font-normal text-gray-400">
                        / 5
                      </span>
                    </p>
                    <p className="mt-1 text-xs text-gray-500 leading-snug">
                      {available ? dim.description : "Data not available"}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>

          {schema != null &&
            typeof schema === "object" &&
            Object.keys(schema).length > 0 && (
              <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
                <button
                  type="button"
                  onClick={() => setSchemaExpanded((p) => !p)}
                  className="w-full flex items-center justify-between px-6 py-4 text-left"
                >
                  <h3 className="text-sm font-semibold text-gray-700">
                    OntoQA / schema metrics
                  </h3>
                  <span className="text-gray-400 text-lg">
                    {schemaExpanded ? "−" : "+"}
                  </span>
                </button>
                {schemaExpanded && (
                  <div className="px-6 pb-6">
                    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
                      {Object.entries(schema).map(([key, val]) => (
                        <div
                          key={key}
                          className="bg-gray-50 rounded-lg border border-gray-100 p-3"
                        >
                          <p className="text-[11px] text-gray-500">
                            {SCHEMA_METRIC_LABELS[key] ??
                              key.replace(/_/g, " ")}
                          </p>
                          <p className="mt-1 text-sm font-semibold text-gray-800">
                            {typeof val === "number"
                              ? formatSchemaValue(key, val)
                              : String(val)}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
        </div>
      </div>
    </div>
  );
}
