"use client";

/**
 * Subsumption review queue (PRD §6.2 FR-2.20).
 *
 * The extraction judge tests every proposed "X is a kind of Y" against the one
 * question that decides it — is every X a Y? — and flags the failures instead
 * of deleting them, because a curator can act on a flagged edge and cannot act
 * on one that vanished. This is where those flags get acted on.
 *
 * Two rulings, because there are only two conclusions to reach:
 *
 *   Keep     — the judge was wrong; the edge stays and stops being raised.
 *   Detach   — the judge was right; this is part-of or attribute-of, not is-a.
 *
 * Detaching leaves the class without a parent rather than inventing a better
 * one. That is deliberate: naming the relation that *should* hold needs the
 * upper ontology (FR-21.7), and an unparented class is visible and fixable
 * where a wrong parent reads as true.
 *
 * Overlay over the canvas, never a route (ui-architecture rule 9); Esc closes.
 *
 * Backend:
 *   GET  /api/v1/ontology/{id}/subsumption/flagged
 *   POST /api/v1/ontology/{id}/subsumption/{edgeKey}/resolve
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import type { FlaggedSubsumption } from "@/types/curation";

interface Props {
  ontologyId: string;
  ontologyName: string;
  curatorId: string;
  /** Called after a ruling so the canvas can drop or unmark the edge. */
  onResolved?: (edgeKey: string, action: "keep" | "detach") => void;
  onClose: () => void;
}

/** Plain-English gloss for the judge's relation codes. */
const RELATION_LABELS: Record<string, string> = {
  "part-of": "part of",
  "attribute-of": "an attribute of",
  "document-about": "a document about",
  "process-on": "a process on",
  "feature-of": "a feature of",
  unrelated: "unrelated to",
};

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.body.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

export default function SubsumptionReviewOverlay({
  ontologyId,
  ontologyName,
  curatorId,
  onResolved,
  onClose,
}: Props) {
  const [rows, setRows] = useState<FlaggedSubsumption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Load failure and save failure are different states. A failed load means we
  // do not know what is flagged, so the queue must not claim to be empty. A
  // failed save means we know exactly what is flagged and the row must stay
  // put -- a queue that loses items a curator believes they ruled on is worse
  // than one that errors.
  const [loadFailed, setLoadFailed] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<{ data?: FlaggedSubsumption[] }>(
        `/api/v1/ontology/${encodeURIComponent(ontologyId)}/subsumption/flagged`,
      );
      setRows(res.data ?? []);
      setError(null);
      setLoadFailed(false);
    } catch (err) {
      setError(errorMessage(err, "Failed to load the subsumption queue"));
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [ontologyId]);

  useEffect(() => {
    load();
  }, [load]);

  async function resolve(row: FlaggedSubsumption, action: "keep" | "detach") {
    setBusyKey(row.edge_key);
    setError(null);
    try {
      await api.post(
        `/api/v1/ontology/${encodeURIComponent(ontologyId)}/subsumption/` +
          `${encodeURIComponent(row.edge_key)}/resolve`,
        { action, curator_id: curatorId },
      );
      setRows((rs) => rs.filter((r) => r.edge_key !== row.edge_key));
      setToast(
        action === "keep"
          ? `Kept — ${row.child_label} stays under ${row.parent_label}`
          : `Detached — ${row.child_label} no longer claims to be a kind of ` +
              `${row.parent_label}, and now has no parent`,
      );
      onResolved?.(row.edge_key, action);
    } catch (err) {
      setError(errorMessage(err, "Failed to record the ruling"));
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <div
      className="fixed top-20 right-6 z-[9000] w-[640px] max-h-[80vh] flex flex-col bg-white rounded-2xl shadow-2xl ring-1 ring-slate-200"
      role="dialog"
      aria-label="Subsumption review"
      data-testid="subsumption-review-overlay"
    >
      <div className="flex items-start justify-between px-5 py-3 border-b border-slate-200">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Subsumption review · {ontologyName}
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Hierarchy links that failed the &ldquo;is every X a Y?&rdquo; test.
          </p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="text-slate-400 hover:text-slate-700"
          data-testid="subsumption-close"
        >
          ✕
        </button>
      </div>

      {error && (
        <div
          className="px-5 py-2 text-sm text-rose-700 bg-rose-50"
          data-testid="subsumption-error"
        >
          {error}
        </div>
      )}
      {toast && (
        <div
          className="px-5 py-2 text-sm text-emerald-700 bg-emerald-50"
          data-testid="subsumption-toast"
        >
          {toast}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-5">
        {loading ? (
          <div
            className="text-sm text-slate-400"
            data-testid="subsumption-loading"
          >
            Loading…
          </div>
        ) : loadFailed ? (
          /* Deliberately not the empty state: after a failed load we do not
             know that nothing is flagged, and saying so would be a lie the
             curator has no way to catch. The error banner above says what
             happened; this space stays silent. */
          <div data-testid="subsumption-load-failed" />
        ) : rows.length === 0 ? (
          <div
            className="text-sm text-slate-400"
            data-testid="subsumption-empty"
          >
            Nothing flagged. Every hierarchy link in this ontology either passed
            the judge or has already been ruled on.
          </div>
        ) : (
          <>
            <p
              className="text-xs text-slate-500 mb-3"
              data-testid="subsumption-count"
            >
              {rows.length} link{rows.length === 1 ? "" : "s"} awaiting a
              ruling.
            </p>
            <ul className="space-y-2" data-testid="subsumption-list">
              {rows.map((r) => {
                const busy = busyKey === r.edge_key;
                const gloss = r.relation
                  ? (RELATION_LABELS[r.relation] ?? r.relation)
                  : null;
                return (
                  <li
                    key={r.edge_key}
                    className="border border-amber-200 bg-amber-50/40 rounded-lg px-3 py-2.5"
                    data-testid={`flagged-${r.edge_key}`}
                  >
                    <p className="text-sm text-slate-800">
                      Is every <strong>{r.child_label}</strong> a{" "}
                      <strong>{r.parent_label}</strong>?
                    </p>
                    {gloss && (
                      <p className="text-xs text-slate-600 mt-1">
                        The judge says it is <strong>{gloss}</strong> it.
                      </p>
                    )}
                    {r.reason && (
                      <p
                        className="text-xs text-slate-500 mt-0.5"
                        data-testid={`reason-${r.edge_key}`}
                      >
                        {r.reason}
                      </p>
                    )}
                    <div className="flex items-center gap-2 mt-2">
                      <button
                        onClick={() => resolve(r, "detach")}
                        disabled={busy}
                        className="px-2.5 py-1 rounded bg-rose-600 text-white text-xs disabled:opacity-40"
                        data-testid={`detach-${r.edge_key}`}
                      >
                        Remove the link
                      </button>
                      <button
                        onClick={() => resolve(r, "keep")}
                        disabled={busy}
                        className="px-2.5 py-1 rounded bg-slate-100 text-slate-700 text-xs disabled:opacity-40"
                        data-testid={`keep-${r.edge_key}`}
                      >
                        It is correct — keep it
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
