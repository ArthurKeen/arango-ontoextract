"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, type PaginatedResponse } from "@/lib/api-client";
import type { OntologyRegistryEntry } from "@/types/curation";
import OntologyCard from "@/components/library/OntologyCard";
import ClassHierarchy from "@/components/library/ClassHierarchy";

export default function LibraryPage() {
  const router = useRouter();
  const [ontologies, setOntologies] = useState<OntologyRegistryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedOntologyId, setSelectedOntologyId] = useState<string | null>(
    null,
  );
  const [tierFilter, setTierFilter] = useState<"all" | "domain" | "local">(
    "all",
  );

  const fetchOntologies = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<PaginatedResponse<OntologyRegistryEntry>>(
        "/api/v1/ontology/library",
      );
      setOntologies(res.data);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.body.message
          : "Failed to load ontology library",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOntologies();
  }, [fetchOntologies]);

  const filtered =
    tierFilter === "all"
      ? ontologies
      : ontologies.filter((o) => o.tier === tierFilter);

  const selectedOntology = ontologies.find(
    (o) => o._key === selectedOntologyId,
  );

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      {/* Header */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-[1600px] mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              Ontology Library
            </h1>
            <p className="text-sm text-gray-500">
              Browse registered ontologies and explore class hierarchies.
            </p>
          </div>
          <a
            href="/"
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Home
          </a>
        </div>
      </header>

      <div className="max-w-[1600px] mx-auto px-6 py-6">
        {/* Filters */}
        <div className="flex items-center gap-3 mb-6">
          <span className="text-sm text-gray-500">Filter:</span>
          {(["all", "domain", "local"] as const).map((tier) => (
            <button
              key={tier}
              onClick={() => setTierFilter(tier)}
              className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                tierFilter === tier
                  ? "bg-blue-50 text-blue-700 border-blue-200 font-medium"
                  : "text-gray-500 border-gray-200 hover:bg-gray-50"
              }`}
              data-testid={`filter-${tier}`}
            >
              {tier === "all"
                ? `All (${ontologies.length})`
                : tier === "domain"
                  ? `Domain (${ontologies.filter((o) => o.tier === "domain").length})`
                  : `Local (${ontologies.filter((o) => o.tier === "local").length})`}
            </button>
          ))}
        </div>

        {loading && (
          <div className="text-center py-12">
            <p className="text-gray-400 animate-pulse">
              Loading ontology library...
            </p>
          </div>
        )}

        {error && (
          <div className="text-center py-12">
            <p className="text-red-500 mb-3">{error}</p>
            <button
              onClick={fetchOntologies}
              className="text-sm px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              Retry
            </button>
          </div>
        )}

        {!loading && !error && (
          <div className="flex gap-6">
            {/* Ontology cards grid */}
            <div className="flex-[7]">
              {filtered.length === 0 ? (
                <div className="text-center py-12 text-gray-400">
                  <p className="text-lg">No ontologies found.</p>
                  <p className="text-sm mt-1">
                    Upload a document and run extraction to create one.
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {filtered.map((ontology) => (
                    <OntologyCard
                      key={ontology._key}
                      ontology={ontology}
                      onClick={(key) => setSelectedOntologyId(key)}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* Class hierarchy panel */}
            {selectedOntology && (
              <aside className="flex-[3] bg-white rounded-xl border border-gray-200 shadow-sm p-4 self-start sticky top-6">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h2 className="text-sm font-semibold text-gray-800">
                      {selectedOntology.name}
                    </h2>
                    <p className="text-xs text-gray-500">Class Hierarchy</p>
                  </div>
                  <button
                    onClick={() => setSelectedOntologyId(null)}
                    className="text-gray-400 hover:text-gray-600 text-lg leading-none"
                    aria-label="Close hierarchy"
                  >
                    &times;
                  </button>
                </div>
                <ClassHierarchy
                  ontologyId={selectedOntology.ontology_id}
                  onClassSelect={(key) =>
                    router.push(`/curation/${key}`)
                  }
                />
              </aside>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
