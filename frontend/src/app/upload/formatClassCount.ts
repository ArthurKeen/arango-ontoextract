/**
 * Rendering an ontology's class count in the upload pickers.
 *
 * Two counts, deliberately kept apart. An ontology's OWN classes are the ones
 * a curator edits; its IMPORTED ones come from the `owl:imports` closure and
 * are read-only foundations belonging to the ontology that defines them.
 * Folding them into a single number would imply you can edit what you cannot.
 *
 * Reporting only the first was its own kind of wrong: "Vehicle Ontology
 * (0 classes)" was created empty importing VSSo, so the picker said 0 while
 * opening it on the canvas showed 516 — the canvas resolves the closure. Same
 * ontology, two numbers, after the Create dialog had promised that imported
 * classes would be available as foundations.
 *
 * The count can also be genuinely unknown: `ontology_registry.class_count` was
 * only ever written by the extraction path, so every IMPORTED ontology carried
 * a null and `{o.class_count} classes` rendered "( classes)" — an empty slot
 * where the number belongs. The backend derives it now, but the UI should not
 * depend on that to stay readable.
 */

/** `"516 classes"` / `"1 class"`, or `null` when the count is unknown. */
export function classCountPhrase(
  count: number | null | undefined,
): string | null {
  if (typeof count !== "number" || Number.isNaN(count)) return null;
  return `${count} ${count === 1 ? "class" : "classes"}`;
}

/**
 * `" (12 classes)"`, `" (0 classes, 516 imported)"`, or `""` when unknown.
 *
 * An absent count renders as nothing rather than an empty pair of brackets:
 * showing "( classes)" tells the reader the UI is broken, showing the name
 * alone tells them only that the number is unavailable. Zero is always shown —
 * that is how an ontology awaiting its first extraction identifies itself, and
 * with an import beside it, how it says "everything here is borrowed".
 *
 * The imported half appears only when there is one, so the common case stays
 * short.
 */
export function formatClassCount(
  count: number | null | undefined,
  importedCount?: number | null,
): string {
  const phrase = classCountPhrase(count);
  if (!phrase) return "";
  const imported =
    typeof importedCount === "number" && importedCount > 0
      ? `, ${importedCount} imported`
      : "";
  return ` (${phrase}${imported})`;
}
