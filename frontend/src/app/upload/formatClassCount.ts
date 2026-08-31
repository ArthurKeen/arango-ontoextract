/**
 * Rendering an ontology's class count in the upload pickers.
 *
 * The count can legitimately be unknown. `ontology_registry.class_count` was
 * only ever written by the extraction path, so every IMPORTED ontology carried
 * a null and `{o.class_count} classes` rendered "( classes)" — an empty slot
 * where the number belongs. The backend now derives the count, but the UI
 * should not depend on that to stay readable.
 */

/** `"516 classes"` / `"1 class"`, or `null` when the count is unknown. */
export function classCountPhrase(
  count: number | null | undefined,
): string | null {
  if (typeof count !== "number" || Number.isNaN(count)) return null;
  return `${count} ${count === 1 ? "class" : "classes"}`;
}

/**
 * `" (12 classes)"` / `" (1 class)"` / `""` when the count is unknown.
 *
 * An absent count renders as nothing rather than an empty pair of brackets:
 * showing "( classes)" tells the reader the UI is broken, showing the name
 * alone tells them only that the number is unavailable. Zero is a real and
 * useful answer and is always shown — that is how an empty ontology created
 * for a pending extraction identifies itself.
 */
export function formatClassCount(count: number | null | undefined): string {
  const phrase = classCountPhrase(count);
  return phrase ? ` (${phrase})` : "";
}
