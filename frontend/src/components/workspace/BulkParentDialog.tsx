"use client";

/**
 * Give a whole selection the same parent (FR-7.8.20).
 *
 * Two modes, one endpoint:
 *   create   — introduce a superclass: make one class, parent the selection to it
 *   existing — reparent the selection under a class that already exists
 *
 * The first is the core taxonomy-building move on a flat extraction: spot a
 * cluster of siblings, give them a parent. Doing it one class at a time is why
 * the taxonomy never gets built.
 *
 * Partial results are shown rather than swallowed — a cycle or a missing class
 * must not silently strand the rest half-moved.
 */

import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import type { OntologyClass } from "@/types/curation";

interface UndoEntry {
  class_key: string;
  previous_parent_key: string | null;
}

interface BulkReparentResult {
  parent_key: string;
  moved: string[];
  failed: { class_key: string; reason: string }[];
  moved_count: number;
  failed_count: number;
  created_parent?: { _key?: string } | null;
  /** Each moved class's previous parent (FR-7.8.21) — what makes this reversible. */
  undo?: UndoEntry[];
}

interface Props {
  ontologyId: string;
  mode: "create" | "existing";
  classKeys: string[];
  /** Candidates for the "existing" mode; the selection itself is excluded. */
  classes: OntologyClass[];
  onClose: () => void;
  onDone: () => void;
}

export default function BulkParentDialog({
  ontologyId,
  mode,
  classKeys,
  classes,
  onClose,
  onDone,
}: Props) {
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [parentKey, setParentKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkReparentResult | null>(null);
  const [undone, setUndone] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // A class in the selection cannot be its own parent, so exclude the set.
  const candidates = useMemo(() => {
    const chosen = new Set(classKeys);
    return classes
      .filter((c) => !chosen.has(c._key))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [classes, classKeys]);

  const canSubmit =
    !busy && (mode === "create" ? label.trim().length > 0 : parentKey.length > 0);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const body =
        mode === "create"
          ? {
              class_keys: classKeys,
              new_parent_label: label.trim(),
              new_parent_description: description.trim(),
            }
          : { class_keys: classKeys, new_parent_key: parentKey };
      const res = await api.post<BulkReparentResult>(
        `/api/v1/ontology/${encodeURIComponent(ontologyId)}/classes/bulk-reparent`,
        body,
      );
      setResult(res);
      if (res.failed_count === 0) onDone();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.body.message : "Failed to set the parent",
      );
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    if (!result?.undo?.length) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<{ restored_count: number; failed_count: number }>(
        `/api/v1/ontology/${encodeURIComponent(ontologyId)}/classes/bulk-reparent/undo`,
        { entries: result.undo },
      );
      setUndone(
        res.failed_count === 0
          ? `Reversed — ${res.restored_count} classes restored to their previous parents.`
          : `Reversed ${res.restored_count}, ${res.failed_count} could not be restored.`,
      );
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.body.message : "Undo failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[9500] flex items-center justify-center bg-black/40"
      role="dialog"
      aria-label={mode === "create" ? "Introduce superclass" : "Set parent"}
      data-testid="bulk-parent-dialog"
    >
      <div className="w-[520px] max-h-[80vh] overflow-y-auto rounded-2xl bg-white p-5 shadow-2xl">
        <h2 className="text-base font-semibold text-gray-900">
          {mode === "create"
            ? `Introduce a superclass over ${classKeys.length} classes`
            : `Set the parent of ${classKeys.length} classes`}
        </h2>

        {mode === "create" ? (
          <div className="mt-4 space-y-3">
            <label className="block">
              <span className="text-xs font-medium text-gray-600">New superclass name</span>
              <input
                autoFocus
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. Vehicle System"
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                data-testid="superclass-label"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-gray-600">Description (optional)</span>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                data-testid="superclass-description"
              />
            </label>
          </div>
        ) : (
          <label className="mt-4 block">
            <span className="text-xs font-medium text-gray-600">Parent class</span>
            <select
              autoFocus
              value={parentKey}
              onChange={(e) => setParentKey(e.target.value)}
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              data-testid="parent-select"
            >
              <option value="">Choose a class…</option>
              {candidates.map((c) => (
                <option key={c._key} value={c._key}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
        )}

        <p className="mt-3 text-[11px] leading-snug text-gray-500">
          Each class keeps a single parent: any existing <code>subClassOf</code> link is
          retired first. Cycles are rejected, and every change is temporal — reversible
          through the timeline.
        </p>

        {error && (
          <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" data-testid="bulk-parent-error">
            {error}
          </p>
        )}

        {result && (
          <div className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs" data-testid="bulk-parent-result">
            <p className="font-medium text-gray-800">
              {result.moved_count} moved
              {result.failed_count > 0 && `, ${result.failed_count} failed`}
            </p>
            {/* Failures are listed, not summarised away: the user needs to know
                WHICH classes did not move and why before they retry. */}
            {result.failed.map((f) => (
              <p key={f.class_key} className="mt-1 text-red-700">
                {f.class_key}: {f.reason}
              </p>
            ))}
            {/* FR-7.8.21 — the way back. Everything here is temporal and so
                recoverable in principle, but there is no revert for edges, so
                without this a twenty-class reshape is reversible only by hand
                from parents the user was never shown. */}
            {!undone && (result.undo?.length ?? 0) > 0 && (
              <button
                onClick={undo}
                disabled={busy}
                className="mt-2 text-xs font-semibold text-blue-700 underline hover:no-underline disabled:opacity-40"
                data-testid="bulk-parent-undo"
              >
                Undo — restore {result.undo?.length} previous parents
              </button>
            )}
            {undone && (
              <p className="mt-2 text-gray-700" data-testid="bulk-parent-undone">
                {undone}
                {/* A superclass emptied by the undo is reported, not deleted —
                    removing a class the user named is not ours to decide. */}
                {result.created_parent ? " The new superclass was kept." : ""}
              </p>
            )}
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
            data-testid="bulk-parent-cancel"
          >
            {result ? "Close" : "Cancel"}
          </button>
          {!result && (
            <button
              onClick={submit}
              disabled={!canSubmit}
              className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-on-accent hover:brightness-90 disabled:opacity-40"
              data-testid="bulk-parent-submit"
            >
              {busy ? "Working…" : mode === "create" ? "Create & reparent" : "Set parent"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
