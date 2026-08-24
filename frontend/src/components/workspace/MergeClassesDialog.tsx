"use client";

/**
 * Merge a multi-selection into one surviving class (FR-7.8.22).
 *
 * The curator picks the survivor. The system never picks — choosing by
 * confidence or label length would silently discard the name a domain expert
 * would have kept, and the whole point of this dialog is that the naming
 * decision is a judgement.
 *
 * This is the one destructive set action WITHOUT a one-click undo: sources are
 * temporally expired and stay queryable as-of a prior time, but there is no
 * un-merge. The dialog says so rather than implying the reversibility its
 * neighbours in the set menu have.
 */

import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import type { OntologyClass } from "@/types/curation";

interface MergeResult {
  target_key: string;
  merged_version?: Record<string, unknown>;
  expired_sources?: string[];
  edges_recreated?: number;
}

interface Props {
  classKeys: string[];
  classes: OntologyClass[];
  curatorId: string;
  onClose: () => void;
  onDone: () => void;
}

export default function MergeClassesDialog({
  classKeys,
  classes,
  curatorId,
  onClose,
  onDone,
}: Props) {
  const members = useMemo(
    () =>
      classes
        .filter((c) => classKeys.includes(c._key))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [classes, classKeys],
  );

  const [targetKey, setTargetKey] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MergeResult | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const survivor = members.find((m) => m._key === targetKey) ?? null;
  const folded = members.filter((m) => m._key !== targetKey);

  async function submit() {
    if (!targetKey) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<MergeResult>("/api/v1/curation/merge", {
        source_keys: folded.map((m) => m._key),
        target_key: targetKey,
        merged_data: {},
        curator_id: curatorId,
        notes: notes.trim() || null,
      });
      setResult(res);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.body.message : "Merge failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[9500] flex items-center justify-center bg-black/40"
      role="dialog"
      aria-label="Merge classes"
      data-testid="merge-classes-dialog"
    >
      <div className="w-[560px] max-h-[80vh] overflow-y-auto rounded-2xl bg-white p-5 shadow-2xl">
        <h2 className="text-base font-semibold text-gray-900">
          Merge {members.length} classes into one
        </h2>

        {!result && (
          <>
            <p className="mt-1 text-xs text-gray-500">
              Choose which class survives. The others are folded into it.
            </p>

            <div className="mt-3 space-y-1 max-h-[240px] overflow-y-auto">
              {members.map((m) => (
                <label
                  key={m._key}
                  className={`flex items-start gap-2 rounded-lg border px-3 py-2 cursor-pointer ${
                    targetKey === m._key
                      ? "border-blue-400 bg-blue-50"
                      : "border-gray-200 hover:bg-gray-50"
                  }`}
                  data-testid={`merge-option-${m._key}`}
                >
                  <input
                    type="radio"
                    name="survivor"
                    className="mt-0.5"
                    checked={targetKey === m._key}
                    onChange={() => setTargetKey(m._key)}
                  />
                  <span className="flex-1">
                    <span className="text-sm font-medium text-gray-800">{m.label}</span>
                    {m.description && (
                      <span className="block text-[11px] text-gray-500 line-clamp-2">
                        {m.description}
                      </span>
                    )}
                  </span>
                  {typeof m.confidence === "number" && (
                    <span className="text-[10px] text-gray-400 flex-shrink-0">
                      {Math.round(m.confidence * 100)}%
                    </span>
                  )}
                </label>
              ))}
            </div>

            {survivor && (
              <p className="mt-3 text-xs text-gray-700" data-testid="merge-summary">
                <span className="font-medium">{survivor.label}</span> survives.{" "}
                {folded.length} {folded.length === 1 ? "class is" : "classes are"} folded in:{" "}
                {folded.map((f) => f.label).join(", ")}
              </p>
            )}

            <label className="mt-3 block">
              <span className="text-xs font-medium text-gray-600">Why (optional)</span>
              <input
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="e.g. duplicate concepts from the same source"
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                data-testid="merge-notes"
              />
            </label>

            {/* Not the same reversibility as its neighbours in the set menu, so
                it must not look like it. */}
            <p
              className="mt-3 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-[11px] leading-snug text-amber-900"
              data-testid="merge-warning"
            >
              <span className="font-medium">This cannot be undone in one click.</span> The
              folded classes are retired and their relationships re-pointed at the survivor.
              They stay queryable as of an earlier time through the timeline, but there is no
              un-merge.
            </p>
          </>
        )}

        {error && (
          <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" data-testid="merge-error">
            {error}
          </p>
        )}

        {result && (
          <div className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs" data-testid="merge-result">
            <p className="font-medium text-gray-800">
              Merged into {survivor?.label ?? result.target_key}.
            </p>
            <p className="mt-1 text-gray-600">
              {result.expired_sources?.length ?? folded.length} retired
              {typeof result.edges_recreated === "number" &&
                `, ${result.edges_recreated} relationships re-pointed`}
              .
            </p>
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
            data-testid="merge-cancel"
          >
            {result ? "Close" : "Cancel"}
          </button>
          {!result && (
            <button
              onClick={submit}
              disabled={busy || !targetKey}
              className="rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-on-accent hover:brightness-90 disabled:opacity-40"
              data-testid="merge-submit"
            >
              {busy ? "Merging…" : `Merge ${folded.length} into ${survivor?.label ?? "…"}`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
