"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type PaginatedResponse } from "@/lib/api-client";

interface OntologyEntry {
  _key: string;
  name?: string;
  label?: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: (ontologyId: string) => void;
}

export default function CreateOntologyDialog({
  open,
  onClose,
  onCreated,
}: Props) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tier, setTier] = useState<"local" | "domain">("local");
  const [selectedImports, setSelectedImports] = useState<string[]>([]);
  // Competency questions, authorable HERE because this is the moment they can
  // still steer the first extraction (FR-19.4 injects their term set into the
  // prompt). Previously they could only be added afterwards, via a
  // right-click → "Requirements & Coverage…" on an ontology that by then had
  // usually already been extracted into.
  const [purpose, setPurpose] = useState("");
  const [questions, setQuestions] = useState<string[]>([""]);
  const [availableOntologies, setAvailableOntologies] = useState<
    OntologyEntry[]
  >([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName("");
    setDescription("");
    setTier("local");
    setSelectedImports([]);
    setPurpose("");
    setQuestions([""]);
    setError(null);

    api
      .get<PaginatedResponse<OntologyEntry>>(
        "/api/v1/ontology/library?limit=100",
      )
      .then((res) => setAvailableOntologies(res.data ?? []))
      .catch(() => setAvailableOntologies([]));
  }, [open]);

  const handleCreate = useCallback(async () => {
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const result = await api.post<{
        ontology_id: string;
        warnings: string[];
      }>("/api/v1/ontology/create", {
        name: name.trim(),
        description: description.trim(),
        tier,
        imports: selectedImports,
      });
      if (result.warnings?.length) {
        console.warn("Create ontology warnings:", result.warnings);
      }
      // Requirements are a SEPARATE, non-fatal step. The ontology exists by
      // now; failing to attach questions to it must not read as "create
      // failed" and must not lose the ontology the user just made.
      const asked = questions.map((q) => q.trim()).filter(Boolean);
      if (purpose.trim() || asked.length) {
        try {
          await api.put(
            `/api/v1/ontology/${encodeURIComponent(result.ontology_id)}/requirements`,
            {
              purpose: purpose.trim() || null,
              use_cases: asked.length
                ? [
                    {
                      name: "Initial scope",
                      priority: "medium",
                      competency_questions: asked.map((text) => ({
                        text,
                        priority: "medium",
                        status: "proposed",
                      })),
                    },
                  ]
                : [],
            },
          );
        } catch (reqErr) {
          console.warn(
            "Ontology created; requirements were not saved:",
            reqErr,
          );
        }
      }
      onCreated(result.ontology_id);
      onClose();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to create ontology",
      );
    } finally {
      setCreating(false);
    }
  }, [
    name,
    description,
    tier,
    selectedImports,
    purpose,
    questions,
    onCreated,
    onClose,
  ]);

  const toggleImport = useCallback((key: string) => {
    setSelectedImports((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );
  }, []);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-[520px] max-h-[90vh] overflow-y-auto">
        <div className="px-6 py-5 border-b border-gray-100">
          <h2 className="text-lg font-semibold text-gray-900">
            Create New Ontology
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            Create an empty ontology and optionally import existing ontologies
            into it.
          </p>
        </div>

        <div className="px-6 py-5 space-y-5">
          <div>
            <label
              htmlFor="ont-name"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Name <span className="text-red-500">*</span>
            </label>
            <input
              id="ont-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Financial Services Domain"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              autoFocus
            />
          </div>

          <div>
            <label
              htmlFor="ont-desc"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Description
            </label>
            <textarea
              id="ont-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional description of this ontology"
              rows={2}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 resize-none"
            />
          </div>

          <div>
            <label
              htmlFor="ont-tier"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Tier
            </label>
            <select
              id="ont-tier"
              value={tier}
              onChange={(e) => setTier(e.target.value as "local" | "domain")}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            >
              <option value="local">Local (organization-specific)</option>
              <option value="domain">Domain (shared standard)</option>
            </select>
          </div>

          <div>
            <label
              htmlFor="ont-purpose"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Competency questions{" "}
              <span className="font-normal text-gray-500">(optional)</span>
            </label>
            <p className="text-xs text-gray-500 mb-2">
              What must this ontology be able to answer? These steer the first
              extraction, and you can refine them later under Requirements &amp;
              Coverage.
            </p>
            <input
              id="ont-purpose"
              type="text"
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              placeholder="Purpose, e.g. Support tyre maintenance scheduling"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            />
            <div className="mt-2 space-y-2">
              {questions.map((q, i) => (
                <div key={i} className="flex gap-2">
                  <input
                    type="text"
                    value={q}
                    onChange={(e) =>
                      setQuestions((qs) =>
                        qs.map((x, idx) => (idx === i ? e.target.value : x)),
                      )
                    }
                    placeholder={
                      i === 0
                        ? "e.g. Which tyres are due for replacement?"
                        : "Another question…"
                    }
                    aria-label={`Competency question ${i + 1}`}
                    data-testid={`cq-input-${i}`}
                    className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                  />
                  {questions.length > 1 && (
                    <button
                      type="button"
                      onClick={() =>
                        setQuestions((qs) => qs.filter((_, idx) => idx !== i))
                      }
                      aria-label={`Remove question ${i + 1}`}
                      className="px-2 text-gray-400 hover:text-gray-700"
                    >
                      ✕
                    </button>
                  )}
                </div>
              ))}
              <button
                type="button"
                onClick={() => setQuestions((qs) => [...qs, ""])}
                data-testid="cq-add"
                className="text-xs text-indigo-600 hover:text-indigo-800"
              >
                + Add question
              </button>
            </div>
          </div>

          {availableOntologies.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Import Ontologies
              </label>
              <p className="text-xs text-gray-500 mb-2">
                Select existing ontologies to import. Imported classes and
                properties will be available as foundations for this ontology.
              </p>
              <div className="border border-gray-200 rounded-lg max-h-[200px] overflow-y-auto divide-y divide-gray-100">
                {availableOntologies.map((ont) => {
                  const displayName = ont.name || ont.label || ont._key;
                  const checked = selectedImports.includes(ont._key);
                  return (
                    <label
                      key={ont._key}
                      className={`flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-gray-50 transition-colors ${
                        checked ? "bg-indigo-50" : ""
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleImport(ont._key)}
                        className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                      />
                      <span className="text-sm text-gray-700 truncate">
                        {displayName}
                      </span>
                    </label>
                  );
                })}
              </div>
              {selectedImports.length > 0 && (
                <p className="text-xs text-indigo-600 mt-1.5">
                  {selectedImports.length} ontolog
                  {selectedImports.length === 1 ? "y" : "ies"} selected
                </p>
              )}
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={creating}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleCreate}
            disabled={creating || !name.trim()}
            className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:brightness-90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {creating ? "Creating…" : "Create Ontology"}
          </button>
        </div>
      </div>
    </div>
  );
}
