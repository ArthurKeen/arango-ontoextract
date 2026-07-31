"use client";

/**
 * A-box instance lens (Stream 21 AB-PR6, PRD §6.18 FR-18.9).
 *
 * Lists the named individuals (instances) extracted for the open ontology, each
 * with its rdf:type class and how many source spans it was grounded in, and lets
 * a curator approve / reject / edit each one (FR-18.9). Reject is a temporal
 * soft-delete (the fact stays queryable as-of a past time); edit relabels the
 * individual.
 *
 * Overlay over the canvas, never a route (ui-architecture rule 9); Esc closes.
 *
 * Backend:
 *   GET  /api/v1/ontology/{id}/individuals
 *   POST /api/v1/ontology/individuals/{key}/curate  { action, label?, class_key? }
 */

import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api-client";

interface IndividualRow {
  _key: string;
  label: string;
  type_label?: string | null;
  type_key?: string | null;
  provenance?: Array<Record<string, unknown>> | null;
}

type CurationAction = "approve" | "reject" | "edit";
type RowStatus = "approved" | "rejected";

interface Props {
  ontologyId: string;
  ontologyName: string;
  onClose: () => void;
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.body.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

export default function IndividualsOverlay({ ontologyId, ontologyName, onClose }: Props) {
  const [rows, setRows] = useState<IndividualRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [statuses, setStatuses] = useState<Record<string, RowStatus>>({});
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editLabel, setEditLabel] = useState("");
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await api.get<{ data?: IndividualRow[] }>(
          `/api/v1/ontology/${encodeURIComponent(ontologyId)}/individuals?limit=500`,
        );
        if (!cancelled) setRows(res.data ?? []);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err, "Failed to load individuals"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ontologyId]);

  async function curate(key: string, action: CurationAction, label?: string) {
    setBusyKey(key);
    setError(null);
    try {
      const body: { action: CurationAction; label?: string } = { action };
      if (label !== undefined) body.label = label;
      await api.post(`/api/v1/ontology/individuals/${encodeURIComponent(key)}/curate`, body);
      if (action === "reject") {
        // Soft-deleted: drop it from the live list.
        setRows((rs) => rs.filter((r) => r._key !== key));
        setToast("Individual rejected (soft-deleted; recoverable from history)");
      } else if (action === "approve") {
        setStatuses((s) => ({ ...s, [key]: "approved" }));
        setToast("Individual approved");
      } else {
        if (label !== undefined) {
          setRows((rs) => rs.map((r) => (r._key === key ? { ...r, label } : r)));
        }
        setEditingKey(null);
        setToast("Individual updated");
      }
    } catch (err) {
      setError(errorMessage(err, `Failed to ${action} individual`));
    } finally {
      setBusyKey(null);
    }
  }

  function startEdit(row: IndividualRow) {
    setEditingKey(row._key);
    setEditLabel(row.label);
  }

  return (
    <div
      className="fixed top-20 right-6 z-[9000] w-[560px] max-h-[80vh] flex flex-col bg-white rounded-2xl shadow-2xl ring-1 ring-slate-200"
      role="dialog"
      aria-label="Instances"
      data-testid="individuals-overlay"
    >
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200">
        <h2 className="text-base font-semibold text-slate-900">
          Instances (A-box) · {ontologyName}
        </h2>
        <button
          onClick={onClose}
          aria-label="Close"
          className="text-slate-400 hover:text-slate-700"
          data-testid="individuals-close"
        >
          ✕
        </button>
      </div>

      {error && (
        <div className="px-5 py-2 text-sm text-rose-700 bg-rose-50" data-testid="individuals-error">
          {error}
        </div>
      )}
      {toast && (
        <div
          className="px-5 py-2 text-sm text-emerald-700 bg-emerald-50"
          data-testid="individuals-toast"
        >
          {toast}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-5">
        {loading ? (
          <div className="text-sm text-slate-400" data-testid="individuals-loading">
            Loading…
          </div>
        ) : rows.length === 0 ? (
          <div className="text-sm text-slate-400" data-testid="individuals-empty">
            No individuals extracted for this ontology yet.
          </div>
        ) : (
          <ul className="space-y-1" data-testid="individuals-list">
            {rows.map((r) => {
              const spans = Array.isArray(r.provenance) ? r.provenance.length : 0;
              const status = statuses[r._key];
              const busy = busyKey === r._key;
              const editing = editingKey === r._key;
              return (
                <li
                  key={r._key}
                  className="group flex items-center justify-between border border-slate-100 rounded px-3 py-2 text-sm"
                  data-testid={`individual-${r._key}`}
                >
                  {editing ? (
                    <div className="flex items-center gap-2 flex-1">
                      <input
                        value={editLabel}
                        onChange={(e) => setEditLabel(e.target.value)}
                        className="flex-1 border border-slate-300 rounded px-2 py-1 text-sm"
                        data-testid={`individual-edit-input-${r._key}`}
                        aria-label="Edit label"
                        autoFocus
                      />
                      <button
                        onClick={() => curate(r._key, "edit", editLabel.trim())}
                        disabled={busy || !editLabel.trim()}
                        className="px-2 py-1 rounded bg-sky-600 text-white text-xs disabled:opacity-40"
                        data-testid={`individual-edit-save-${r._key}`}
                      >
                        Save
                      </button>
                      <button
                        onClick={() => setEditingKey(null)}
                        className="px-2 py-1 rounded bg-slate-100 text-slate-600 text-xs"
                        data-testid={`individual-edit-cancel-${r._key}`}
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <>
                      <span className="font-medium text-slate-800 flex items-center gap-2">
                        {r.label}
                        {status === "approved" && (
                          <span
                            className="px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 text-[10px]"
                            data-testid={`individual-status-${r._key}`}
                          >
                            approved
                          </span>
                        )}
                      </span>
                      <span className="flex items-center gap-2 text-xs text-slate-500">
                        {r.type_label && (
                          <span
                            className="px-2 py-0.5 rounded-full bg-slate-100"
                            data-testid={`individual-type-${r._key}`}
                          >
                            {r.type_label}
                          </span>
                        )}
                        <span title="source spans">📎 {spans}</span>
                        <span className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => curate(r._key, "approve")}
                            disabled={busy}
                            title="Approve"
                            aria-label="Approve"
                            className="text-emerald-600 hover:text-emerald-800 disabled:opacity-40"
                            data-testid={`individual-approve-${r._key}`}
                          >
                            ✓
                          </button>
                          <button
                            onClick={() => startEdit(r)}
                            disabled={busy}
                            title="Edit label"
                            aria-label="Edit"
                            className="text-sky-600 hover:text-sky-800 disabled:opacity-40"
                            data-testid={`individual-edit-${r._key}`}
                          >
                            ✏️
                          </button>
                          <button
                            onClick={() => curate(r._key, "reject")}
                            disabled={busy}
                            title="Reject (soft-delete)"
                            aria-label="Reject"
                            className="text-rose-600 hover:text-rose-800 disabled:opacity-40"
                            data-testid={`individual-reject-${r._key}`}
                          >
                            🗑
                          </button>
                        </span>
                      </span>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
