"use client";

/**
 * Label-collision work queue (PRD §6.20 FR-20.1..FR-20.3).
 *
 * Brings a colliding label to a curator with everything needed to judge it —
 * which concepts carry it, which system each came from, and sample values where
 * a producer supplied them — then records the chosen label per concept as a
 * decision with attribution.
 *
 * Deciding is per-occurrence and partial by design: leaving one side alone is
 * often the right answer, so an empty box means "no change", not "blank it".
 *
 * Overlay over the canvas, never a route (ui-architecture rule 9); Esc closes.
 *
 * Backend:
 *   GET  /api/v1/ontology/lexicon/collisions?status=open
 *   POST /api/v1/ontology/lexicon/collisions/detect
 *   POST /api/v1/ontology/lexicon/collisions/{key}/resolve
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import type { LabelCollision } from "@/types/curation";

interface Props {
  ontologyId: string;
  ontologyName: string;
  curatorId: string;
  onClose: () => void;
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.body.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

export default function LexiconQueueOverlay({
  ontologyId,
  ontologyName,
  curatorId,
  onClose,
}: Props) {
  const [rows, setRows] = useState<LabelCollision[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  // { [collisionKey]: { [conceptUri]: chosenLabel } }
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({});

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
      const res = await api.get<{ data?: LabelCollision[] }>(
        "/api/v1/ontology/lexicon/collisions?status=open&limit=200",
      );
      setRows(res.data ?? []);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, "Failed to load the collision queue"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function scan() {
    setScanning(true);
    setError(null);
    try {
      const res = await api.post<{ detected: number; skipped_stopwords: number }>(
        "/api/v1/ontology/lexicon/collisions/detect",
        { ontology_ids: [ontologyId] },
      );
      setToast(
        `Scan complete — ${res.detected} collision${res.detected === 1 ? "" : "s"}` +
          (res.skipped_stopwords
            ? `, ${res.skipped_stopwords} generic label${
                res.skipped_stopwords === 1 ? "" : "s"
              } skipped`
            : ""),
      );
      await load();
    } catch (err) {
      setError(errorMessage(err, "Scan failed"));
    } finally {
      setScanning(false);
    }
  }

  function setDraft(collisionKey: string, conceptUri: string, label: string) {
    setDrafts((prev) => ({
      ...prev,
      [collisionKey]: { ...(prev[collisionKey] ?? {}), [conceptUri]: label },
    }));
  }

  async function resolve(collision: LabelCollision) {
    const draft = drafts[collision._key] ?? {};
    const resolutions = collision.occurrences
      .filter((o) => (draft[o.concept_uri] ?? "").trim().length > 0)
      .map((o) => ({
        concept_uri: o.concept_uri,
        label: (draft[o.concept_uri] ?? "").trim(),
        concept_type: o.concept_type ?? "datatype_property",
        ontology_id: o.ontology_id ?? null,
      }));

    if (resolutions.length === 0) {
      setError("Enter a label for at least one concept, or dismiss the collision.");
      return;
    }

    setBusyKey(collision._key);
    setError(null);
    try {
      await api.post(
        `/api/v1/ontology/lexicon/collisions/${encodeURIComponent(collision._key)}/resolve`,
        { curator_id: curatorId, resolutions },
      );
      setRows((rs) => rs.filter((r) => r._key !== collision._key));
      setToast(
        `Recorded ${resolutions.length} decision${resolutions.length === 1 ? "" : "s"} — ` +
          "these labels now survive re-extraction",
      );
    } catch (err) {
      setError(errorMessage(err, "Failed to record the decision"));
    } finally {
      setBusyKey(null);
    }
  }

  async function dismiss(collision: LabelCollision) {
    setBusyKey(collision._key);
    setError(null);
    try {
      await api.post(
        `/api/v1/ontology/lexicon/collisions/${encodeURIComponent(collision._key)}/resolve`,
        { curator_id: curatorId, dismiss: true },
      );
      setRows((rs) => rs.filter((r) => r._key !== collision._key));
      setToast("Collision dismissed — it will not be re-opened by a later scan");
    } catch (err) {
      setError(errorMessage(err, "Failed to dismiss"));
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <div
      className="fixed top-20 right-6 z-[9000] w-[640px] max-h-[80vh] flex flex-col bg-white rounded-2xl shadow-2xl ring-1 ring-slate-200"
      role="dialog"
      aria-label="Label collisions"
      data-testid="lexicon-queue-overlay"
    >
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200">
        <h2 className="text-base font-semibold text-slate-900">
          Label collisions · {ontologyName}
        </h2>
        <div className="flex items-center gap-3">
          <button
            onClick={scan}
            disabled={scanning}
            className="text-xs px-2.5 py-1 rounded-lg bg-sky-600 text-white disabled:opacity-40"
            data-testid="lexicon-scan"
          >
            {scanning ? "Scanning…" : "Scan this ontology"}
          </button>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-slate-400 hover:text-slate-700"
            data-testid="lexicon-close"
          >
            ✕
          </button>
        </div>
      </div>

      {error && (
        <div className="px-5 py-2 text-sm text-rose-700 bg-rose-50" data-testid="lexicon-error">
          {error}
        </div>
      )}
      {toast && (
        <div
          className="px-5 py-2 text-sm text-emerald-700 bg-emerald-50"
          data-testid="lexicon-toast"
        >
          {toast}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-5">
        {loading ? (
          <div className="text-sm text-slate-400" data-testid="lexicon-loading">
            Loading…
          </div>
        ) : rows.length === 0 ? (
          <div className="text-sm text-slate-400" data-testid="lexicon-empty">
            No open label collisions. Run a scan to check this ontology.
          </div>
        ) : (
          <ul className="space-y-2" data-testid="lexicon-list">
            {rows.map((c) => {
              const open = expanded === c._key;
              const busy = busyKey === c._key;
              return (
                <li
                  key={c._key}
                  className="border border-slate-200 rounded-lg"
                  data-testid={`collision-${c._key}`}
                >
                  <button
                    onClick={() => setExpanded(open ? null : c._key)}
                    className="w-full flex items-center justify-between px-3 py-2 text-sm"
                    data-testid={`collision-toggle-${c._key}`}
                  >
                    <span className="font-medium text-slate-800">
                      <code className="px-1 bg-slate-100 rounded">{c.label}</code>
                    </span>
                    <span className="text-xs text-slate-500">
                      {c.occurrence_count ?? c.occurrences.length} concepts
                      {c.source === "local" ? " · detected here" : ` · via ${c.source}`}
                      <span className="ml-2">{open ? "▾" : "▸"}</span>
                    </span>
                  </button>

                  {open && (
                    <div className="px-3 pb-3 space-y-3 border-t border-slate-100 pt-3">
                      {c.occurrences.map((o) => (
                        <div
                          key={o.concept_uri}
                          className="space-y-1"
                          data-testid={`occurrence-${o.concept_uri}`}
                        >
                          <div className="flex items-baseline gap-2 text-xs">
                            <span className="font-medium text-slate-700">
                              {o.label || c.label}
                            </span>
                            {o.source_system && (
                              <span className="px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600">
                                {o.source_system}
                              </span>
                            )}
                            {o.concept_type && (
                              <span className="text-slate-400">{o.concept_type}</span>
                            )}
                          </div>
                          <p className="text-[11px] text-slate-500 break-all">{o.concept_uri}</p>
                          {o.description && (
                            <p className="text-[11px] text-slate-600">{o.description}</p>
                          )}
                          {o.sample_values && o.sample_values.length > 0 && (
                            <p
                              className="text-[11px] text-slate-600"
                              data-testid={`samples-${o.concept_uri}`}
                            >
                              e.g.{" "}
                              {o.sample_values.slice(0, 6).map((v, i) => (
                                <span key={`${v}-${i}`}>
                                  {i > 0 && ", "}
                                  <code className="px-1 bg-amber-50 rounded">{v}</code>
                                </span>
                              ))}
                            </p>
                          )}
                          <input
                            value={drafts[c._key]?.[o.concept_uri] ?? ""}
                            onChange={(e) => setDraft(c._key, o.concept_uri, e.target.value)}
                            placeholder="Leave blank to keep this one unchanged"
                            aria-label={`New label for ${o.concept_uri}`}
                            className="w-full border border-slate-300 rounded px-2 py-1 text-sm"
                            data-testid={`label-input-${o.concept_uri}`}
                          />
                        </div>
                      ))}

                      <div className="flex items-center gap-2 pt-1">
                        <button
                          onClick={() => resolve(c)}
                          disabled={busy}
                          className="px-2.5 py-1 rounded bg-emerald-600 text-white text-xs disabled:opacity-40"
                          data-testid={`resolve-${c._key}`}
                        >
                          Record decision
                        </button>
                        <button
                          onClick={() => dismiss(c)}
                          disabled={busy}
                          className="px-2.5 py-1 rounded bg-slate-100 text-slate-600 text-xs disabled:opacity-40"
                          data-testid={`dismiss-${c._key}`}
                        >
                          Not a problem
                        </button>
                      </div>
                    </div>
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
