"use client";

import { useEffect, useState, useCallback } from "react";
import { api, ApiError } from "@/lib/api-client";
import { splitTextByKeywordAlternation } from "@/lib/textHighlight";
import type { SourceChunk } from "@/types/curation";

interface ProvenancePanelProps {
  entityKey: string;
  entityLabel: string;
  onClose?: () => void;
}

interface RankedChunkFields {
  /** 0–1 support score (FR-4.19). */
  support?: number;
  /** How `support` was derived — shown so the ordering is auditable. */
  support_basis?: "evidence_confidence" | "keyword_density";
}

interface EvidenceItem {
  evidence_text?: string | null;
  evidence_confidence?: number | null;
  extraction_rationale?: string | null;
  source_chunk_ids?: string[] | null;
  source_spans?: string[] | null;
}

interface ChunkResponse {
  data: SourceChunk[];
  total_count: number;
  /** Recorded at extraction (FR-4.7). Empty for pre-evidence classes. */
  evidence?: EvidenceItem[];
  /**
   * ``evidence`` — the chunks the extractor actually used.
   * ``document`` — the pre-evidence fallback: every chunk of every linked
   * document. Coarse, and labelled as such so it cannot pass for evidence.
   */
  level?: "evidence" | "document";
}

function highlightKeywords(text: string, keywords: string[]): JSX.Element {
  if (keywords.length === 0) return <>{text}</>;
  const parts = splitTextByKeywordAlternation(text, keywords);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="bg-yellow-200 rounded px-0.5">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

export default function ProvenancePanel({
  entityKey,
  entityLabel,
  onClose,
}: ProvenancePanelProps) {
  const [chunks, setChunks] = useState<SourceChunk[]>([]);
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [level, setLevel] = useState<"evidence" | "document">("document");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const keywords = entityLabel
    .split(/[\s_-]+/)
    .filter((w) => w.length > 2);

  const fetchChunks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<ChunkResponse>(
        `/api/v1/ontology/class/${entityKey}/provenance`,
      );
      setChunks(res.data);
      setEvidence(res.evidence ?? []);
      setLevel(res.level ?? "document");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.body.message
          : "Failed to load provenance data",
      );
    } finally {
      setLoading(false);
    }
  }, [entityKey]);

  useEffect(() => {
    fetchChunks();
  }, [fetchChunks]);

  return (
    <div className="space-y-3" data-testid="provenance-panel">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-800">
          Source Provenance
        </h3>
        {onClose && (
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-lg leading-none"
            aria-label="Close provenance"
          >
            &times;
          </button>
        )}
      </div>
      <p className="text-xs text-gray-500">
        {level === "evidence" ? "Passages the extractor used for " : "Documents linked to "}
        <span className="font-medium text-gray-700">{entityLabel}</span>
      </p>

      {!loading && !error && level === "document" && chunks.length > 0 && (
        <p
          className="text-[11px] leading-snug text-amber-800 bg-amber-50 border border-amber-200 rounded-md px-2 py-1.5"
          data-testid="provenance-document-level"
        >
          <span className="font-medium">Document-level only.</span> No extraction evidence was
          recorded for this class, so every chunk of each linked document is listed. Highlights are
          keyword matches, not the passage the extractor used — treat this as a starting point, not
          as evidence.
        </p>
      )}

      {!loading && !error && evidence.length > 0 && (
        <div className="space-y-1.5" data-testid="provenance-evidence">
          {evidence.map((ev, i) => (
            <div
              key={i}
              className="text-[11px] leading-snug bg-blue-50 border border-blue-200 rounded-md px-2 py-1.5"
            >
              {ev.evidence_text && (
                <p className="text-gray-800">&ldquo;{ev.evidence_text}&rdquo;</p>
              )}
              {ev.extraction_rationale && (
                <p className="mt-1 text-gray-600">
                  <span className="font-medium">Why:</span> {ev.extraction_rationale}
                </p>
              )}
              {typeof ev.evidence_confidence === "number" && (
                <p className="mt-1 text-gray-500">
                  Confidence {Math.round(ev.evidence_confidence * 100)}%
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {loading && (
        <div className="py-6 text-center text-sm text-gray-400 animate-pulse" data-testid="provenance-loading">
          Loading provenance...
        </div>
      )}

      {error && (
        <div className="py-3 px-3 text-sm text-red-600 bg-red-50 rounded-lg" data-testid="provenance-error">
          {error}
        </div>
      )}

      {!loading && !error && chunks.length === 0 && (
        <div className="py-6 text-center text-sm text-gray-400" data-testid="provenance-empty">
          No source chunks found for this entity.
        </div>
      )}

      {!loading && chunks.length > 0 && (
        <div className="space-y-2 max-h-[400px] overflow-y-auto">
          {chunks.map((chunk, idx) => {
            const ranked = chunk as SourceChunk & RankedChunkFields;
            const isTop = idx === 0 && (ranked.support ?? 0) > 0;
            return (
            <div
              key={chunk._key}
              className={`rounded-lg border p-3 ${
                isTop
                  ? "bg-blue-50 border-blue-200 ring-1 ring-blue-200"
                  : "bg-gray-50 border-gray-100"
              }`}
              data-testid={`chunk-${chunk._key}`}
            >
              <div className="flex items-center gap-2 mb-1.5">
                {/* FR-4.19 — the strongest passage is called out, and the basis
                    is named so a curator can see why it ranked first and
                    disagree. An unexplained ordering is just an assertion. */}
                {isTop && (
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-600 text-on-accent font-medium"
                    data-testid="chunk-top-support"
                  >
                    strongest
                  </span>
                )}
                <span className="text-xs font-medium text-gray-700">
                  {chunk.document_name}
                </span>
                {chunk.page != null && (
                  <span className="text-xs text-gray-400">
                    Page {chunk.page}
                  </span>
                )}
                {chunk.section && (
                  <span className="text-xs text-gray-400">
                    &middot; {chunk.section}
                  </span>
                )}
              </div>
              <p className="text-sm text-gray-600 leading-relaxed">
                {highlightKeywords(chunk.text, keywords)}
              </p>
              {ranked.support_basis && (ranked.support ?? 0) > 0 && (
                <p className="mt-1.5 text-[10px] text-gray-400">
                  {ranked.support_basis === "evidence_confidence"
                    ? `Extractor confidence ${Math.round((ranked.support ?? 0) * 100)}%`
                    : "Ranked by keyword match (no recorded evidence)"}
                </p>
              )}
            </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
