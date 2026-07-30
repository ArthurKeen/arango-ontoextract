"use client";

/**
 * Alignment Review overlay (Stream 20 AL-PR5, PRD §6.17).
 *
 * Makes multi-source ontology alignment demoable in the workspace: pick one or
 * more *other* library ontologies to align with the open one, run alignment,
 * (optionally) let the LLM adjudicate the borderline correspondences, then
 * accept/reject each candidate and materialize a reconciled master ontology.
 *
 * Overlay over the canvas, never a route (ui-architecture rule 9); decisions
 * apply optimistically and re-fetch on failure (rule 18); Esc closes.
 *
 * Backend (see app/api/alignment.py):
 *   POST /api/v1/alignment/sessions                       -- create + generate candidates
 *   POST /api/v1/alignment/sessions/{id}/adjudicate       -- selective LLM adjudication
 *   GET  /api/v1/alignment/sessions/{id}/candidates       -- list correspondences
 *   POST /api/v1/alignment/candidates/{key}/{accept|reject}
 *   POST /api/v1/alignment/sessions/{id}/materialize      -- write the master
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api-client";

interface OntologyRow {
  key: string;
  name: string;
}

interface Correspondence {
  _key: string;
  source_a: { ontology_id: string; entity_key: string; label?: string | null };
  source_b: { ontology_id: string; entity_key: string; label?: string | null };
  scores?: Record<string, number>;
  confidence: number;
  type: string;
  status: string;
  adjudication?: {
    method?: string;
    verdict?: string;
    recommendation?: string;
    // AL-PR8 classical-anchor ensemble signals.
    hallucination?: boolean;
    disagreement?: boolean;
    review_priority?: number;
  } | null;
}

// AL-PR7 coherence-repair removals returned by materialize.
interface RepairRemoval {
  correspondence_key?: string;
  confidence?: number;
  resolves_conflict?: { a?: string[]; b?: string[] };
}

interface SessionResponse {
  _key: string;
  candidate_count: number;
}

interface CandidatesResponse {
  session_id: string;
  candidates: Correspondence[];
  count: number;
}

interface AdjudicateResponse {
  adjudicated: number;
  llm_calls: number;
}

interface MaterializeResponse {
  master_id: string;
  class_count: number;
  equivalence_edges: number;
  repair?: { removed: number; removals: RepairRemoval[] };
}

interface Props {
  ontologyId: string;
  ontologyName: string;
  onClose: () => void;
  /** Called after materialization so the parent can refresh the library. */
  onChanged?: () => void;
}

function errMsg(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.body.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

function confidenceColor(score: number): string {
  if (score >= 0.85) return "bg-emerald-500";
  if (score >= 0.7) return "bg-amber-500";
  return "bg-rose-500";
}

export default function AlignmentReviewOverlay({
  ontologyId,
  ontologyName,
  onClose,
  onChanged,
}: Props) {
  const [library, setLibrary] = useState<OntologyRow[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [phase, setPhase] = useState<"select" | "review">("select");

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<Correspondence[]>([]);
  const [busy, setBusy] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [masterId, setMasterId] = useState<string | null>(null);
  const [repair, setRepair] = useState<{ removed: number; removals: RepairRemoval[] } | null>(
    null,
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Load the library so the user can pick other sources (excluding the open one).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<{ data?: Array<Record<string, unknown>> }>(
          "/api/v1/ontology/library",
        );
        if (cancelled) return;
        const rows = (res.data ?? [])
          .map((o) => ({
            key: String(o._key ?? o.id ?? o.key ?? ""),
            name: String(o.name ?? o._key ?? ""),
          }))
          .filter((o) => o.key && o.key !== ontologyId);
        setLibrary(rows);
      } catch (err) {
        if (!cancelled) setError(errMsg(err, "Failed to load ontologies"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ontologyId]);

  const fetchCandidates = useCallback(async (sid: string) => {
    const res = await api.get<CandidatesResponse>(
      `/api/v1/alignment/sessions/${encodeURIComponent(sid)}/candidates?limit=200`,
    );
    setCandidates(res.candidates ?? []);
  }, []);

  const runAlignment = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const sources = [ontologyId, ...selected];
      const res = await api.post<SessionResponse>("/api/v1/alignment/sessions", {
        source_ontology_ids: sources,
      });
      setSessionId(res._key);
      setPhase("review");
      await fetchCandidates(res._key);
      setToast(`${res.candidate_count} candidate correspondence(s)`);
    } catch (err) {
      setError(errMsg(err, "Failed to run alignment"));
    } finally {
      setBusy(false);
    }
  }, [ontologyId, selected, fetchCandidates]);

  const adjudicate = useCallback(async () => {
    if (!sessionId) return;
    setBusy(true);
    try {
      const res = await api.post<AdjudicateResponse>(
        `/api/v1/alignment/sessions/${encodeURIComponent(sessionId)}/adjudicate`,
      );
      await fetchCandidates(sessionId);
      setToast(`Adjudicated ${res.adjudicated} (LLM on ${res.llm_calls})`);
    } catch (err) {
      setError(errMsg(err, "Adjudication failed"));
    } finally {
      setBusy(false);
    }
  }, [sessionId, fetchCandidates]);

  const decide = useCallback(
    async (key: string, decision: "accept" | "reject") => {
      setBusyKey(key);
      // optimistic
      setCandidates((prev) =>
        prev.map((c) =>
          c._key === key ? { ...c, status: decision === "accept" ? "accepted" : "rejected" } : c,
        ),
      );
      try {
        await api.post(`/api/v1/alignment/candidates/${encodeURIComponent(key)}/${decision}`);
      } catch (err) {
        setError(errMsg(err, "Decision failed"));
        if (sessionId) await fetchCandidates(sessionId); // restore true state
      } finally {
        setBusyKey(null);
      }
    },
    [sessionId, fetchCandidates],
  );

  const materialize = useCallback(async () => {
    if (!sessionId) return;
    setBusy(true);
    try {
      const res = await api.post<MaterializeResponse>(
        `/api/v1/alignment/sessions/${encodeURIComponent(sessionId)}/materialize`,
        {},
      );
      setMasterId(res.master_id);
      setRepair(res.repair ?? null);
      const removed = res.repair?.removed ?? 0;
      setToast(
        `Master ${res.master_id}: ${res.class_count} class(es)` +
          (removed ? `, ${removed} removed for coherence` : ""),
      );
      onChanged?.();
    } catch (err) {
      setError(errMsg(err, "Materialization failed"));
    } finally {
      setBusy(false);
    }
  }, [sessionId, onChanged]);

  const toggle = (key: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const acceptedCount = candidates.filter((c) => c.status === "accepted").length;

  // DualLoop re-rank (FR-17.8): still-pending pairs first, and within those the
  // ones the ensemble flagged (hallucination=2 / disagreement=1) ahead of the
  // rest, then by confidence. Because it derives from `candidates`, each
  // accept/reject re-sorts — decided pairs sink and the next most important
  // borderline pair surfaces to the top of the review queue.
  const reviewPriority = (c: Correspondence): number => c.adjudication?.review_priority ?? 0;
  const sortedCandidates = [...candidates].sort((a, b) => {
    const aPending = a.status === "candidate" ? 0 : 1;
    const bPending = b.status === "candidate" ? 0 : 1;
    if (aPending !== bPending) return aPending - bPending;
    const byPriority = reviewPriority(b) - reviewPriority(a);
    if (byPriority !== 0) return byPriority;
    return b.confidence - a.confidence;
  });

  return (
    <div
      className="fixed top-20 right-6 z-[9000] w-[600px] max-h-[80vh] flex flex-col bg-white rounded-2xl shadow-2xl ring-1 ring-slate-200"
      role="dialog"
      aria-label="Align ontologies"
      data-testid="alignment-review-overlay"
    >
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200">
        <h2 className="text-base font-semibold text-slate-900">
          Align ontologies · {ontologyName}
        </h2>
        <button
          onClick={onClose}
          aria-label="Close"
          className="text-slate-400 hover:text-slate-700"
          data-testid="alignment-close"
        >
          ✕
        </button>
      </div>

      {error && (
        <div className="px-5 py-2 text-sm text-rose-700 bg-rose-50" data-testid="alignment-error">
          {error}
        </div>
      )}
      {toast && (
        <div className="px-5 py-2 text-sm text-slate-600 bg-slate-50" data-testid="alignment-toast">
          {toast}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-5">
        {phase === "select" && (
          <div data-testid="alignment-select">
            <p className="text-sm text-slate-600 mb-3">
              Select one or more ontologies to align with <b>{ontologyName}</b>.
            </p>
            <ul className="space-y-1 mb-4">
              {library.map((o) => (
                <li key={o.key}>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={selected.has(o.key)}
                      onChange={() => toggle(o.key)}
                      data-testid={`alignment-source-${o.key}`}
                    />
                    {o.name}
                  </label>
                </li>
              ))}
              {library.length === 0 && (
                <li className="text-sm text-slate-400">No other ontologies in the library.</li>
              )}
            </ul>
            <button
              onClick={runAlignment}
              disabled={busy || selected.size === 0}
              className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-lg disabled:opacity-40"
              data-testid="alignment-run"
            >
              {busy ? "Aligning…" : `Align ${selected.size + 1} ontologies`}
            </button>
          </div>
        )}

        {phase === "review" && (
          <div data-testid="alignment-review">
            <div className="flex gap-2 mb-3">
              <button
                onClick={adjudicate}
                disabled={busy}
                className="px-3 py-1.5 text-xs font-medium text-slate-700 bg-slate-100 rounded-lg disabled:opacity-40"
                data-testid="alignment-adjudicate"
              >
                Adjudicate borderline (LLM)
              </button>
              <button
                onClick={materialize}
                disabled={busy || acceptedCount === 0}
                className="px-3 py-1.5 text-xs font-medium text-white bg-indigo-600 rounded-lg disabled:opacity-40"
                data-testid="alignment-materialize"
                title={acceptedCount === 0 ? "Accept correspondences first" : ""}
              >
                Materialize master ({acceptedCount})
              </button>
            </div>

            {masterId && (
              <div
                className="mb-3 text-sm text-indigo-700 bg-indigo-50 rounded px-3 py-2"
                data-testid="alignment-master"
              >
                Master ontology created: {masterId}
              </div>
            )}

            {repair && repair.removed > 0 && (
              <div
                className="mb-3 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2"
                data-testid="alignment-repair"
              >
                <div className="font-medium">
                  Coherence repair removed {repair.removed} correspondence
                  {repair.removed === 1 ? "" : "s"} to keep the master satisfiable (a
                  declared-disjoint pair would otherwise have been merged):
                </div>
                <ul className="mt-1 space-y-0.5">
                  {repair.removals.slice(0, 8).map((r, i) => (
                    <li key={r.correspondence_key ?? i} className="text-amber-700">
                      • {r.correspondence_key ?? "?"}
                      {typeof r.confidence === "number"
                        ? ` (confidence ${Math.round(r.confidence * 100)}%)`
                        : ""}
                      {r.resolves_conflict?.a && r.resolves_conflict?.b
                        ? ` — resolved ${(r.resolves_conflict.a ?? []).join("/")} ≢ ${(
                            r.resolves_conflict.b ?? []
                          ).join("/")}`
                        : ""}
                    </li>
                  ))}
                  {repair.removals.length > 8 && (
                    <li className="text-amber-600">+{repair.removals.length - 8} more…</li>
                  )}
                </ul>
              </div>
            )}

            <ul className="space-y-2">
              {sortedCandidates.map((c) => (
                <li
                  key={c._key}
                  className="border border-slate-200 rounded-lg p-3"
                  data-testid={`alignment-candidate-${c._key}`}
                >
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium text-slate-800">
                      {c.source_a.label ?? c.source_a.entity_key} ↔{" "}
                      {c.source_b.label ?? c.source_b.entity_key}
                    </span>
                    <span className="flex items-center gap-1.5">
                      {c.adjudication?.hallucination ? (
                        <span
                          data-testid={`alignment-badge-hallucination-${c._key}`}
                          title="LLM proposed this match with no grounded source anchor — never auto-accepted; confirm with care."
                          className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-rose-100 text-rose-700"
                        >
                          ⚠ hallucination
                        </span>
                      ) : (
                        c.adjudication?.disagreement && (
                          <span
                            data-testid={`alignment-badge-disagreement-${c._key}`}
                            title="LLM verdict disagrees with the classical (lexical/structural) anchor — prioritized for review."
                            className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-amber-100 text-amber-800"
                          >
                            ⚠ disagreement
                          </span>
                        )
                      )}
                      <span className="text-xs text-slate-500">{c.type}</span>
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <div className="h-1.5 w-28 rounded bg-slate-100">
                      <div
                        className={`h-1.5 rounded ${confidenceColor(c.confidence)}`}
                        style={{ width: `${Math.round(c.confidence * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-slate-500">
                      {Math.round(c.confidence * 100)}%
                    </span>
                    {c.adjudication?.recommendation && (
                      <span className="text-xs text-slate-400">
                        · rec: {c.adjudication.recommendation}
                      </span>
                    )}
                  </div>
                  <div className="mt-2 flex gap-2">
                    {c.status === "candidate" ? (
                      <>
                        <button
                          onClick={() => decide(c._key, "accept")}
                          disabled={busyKey === c._key}
                          className="px-2 py-1 text-xs text-emerald-700 bg-emerald-50 rounded disabled:opacity-40"
                          data-testid={`alignment-accept-${c._key}`}
                        >
                          Accept
                        </button>
                        <button
                          onClick={() => decide(c._key, "reject")}
                          disabled={busyKey === c._key}
                          className="px-2 py-1 text-xs text-rose-700 bg-rose-50 rounded disabled:opacity-40"
                          data-testid={`alignment-reject-${c._key}`}
                        >
                          Reject
                        </button>
                      </>
                    ) : (
                      <span
                        className="text-xs text-slate-500"
                        data-testid={`alignment-status-${c._key}`}
                      >
                        {c.status}
                      </span>
                    )}
                  </div>
                </li>
              ))}
              {candidates.length === 0 && (
                <li className="text-sm text-slate-400" data-testid="alignment-empty">
                  No candidate correspondences.
                </li>
              )}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
