"use client";

import Link from "next/link";

export type LensType = "semantic" | "confidence" | "curation" | "diff" | "source";

const LENS_LABELS: Record<LensType, string> = {
  semantic: "Semantic",
  confidence: "Confidence",
  curation: "Curation Status",
  diff: "Diff",
  source: "Source Type",
};

interface LensToolbarProps {
  activeLens: LensType;
  onLensChange: (lens: LensType) => void;
  selectedOntologyId: string | null;
  selectedOntologyName?: string;
}

export default function LensToolbar({
  activeLens,
  onLensChange: _onLensChange,
  selectedOntologyId,
  selectedOntologyName,
}: LensToolbarProps) {
  return (
    <header className="h-11 border-b border-gray-800 bg-[#12121f] flex items-center px-4 gap-4 flex-shrink-0">
      {/* Logo — left side */}
      <Link
        href="/"
        className="flex items-center gap-1.5 text-gray-100 hover:text-white transition-colors"
        title="AOE Home"
      >
        <span className="text-sm font-bold tracking-widest">AOE</span>
      </Link>

      <div className="flex-1" />

      {/* Right side: ontology indicator + lens badge */}
      {selectedOntologyId && (
        <div className="flex items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5 text-gray-400">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
            <span className="font-medium text-gray-200 truncate max-w-[220px]">
              {selectedOntologyName ?? selectedOntologyId}
            </span>
          </div>
          <span className="text-gray-500">
            ({LENS_LABELS[activeLens]} view)
          </span>
        </div>
      )}
    </header>
  );
}
