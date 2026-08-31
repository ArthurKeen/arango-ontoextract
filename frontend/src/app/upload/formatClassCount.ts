/**
 * Render an ontology's class count for the target-ontology picker.
 *
 * `" (12 classes)"` / `" (1 class)"` / `""` when the count is unknown.
 *
 * An absent count renders as nothing rather than an empty pair of brackets:
 * showing "( classes)" tells the reader the UI is broken, showing the name
 * alone tells them only that the number is unavailable. Zero is a real and
 * useful answer and is always shown — that is how an empty ontology created
 * for a pending extraction identifies itself.
 */
export function formatClassCount(count: number | null | undefined): string {
  if (typeof count !== "number" || Number.isNaN(count)) return "";
  return ` (${count} ${count === 1 ? "class" : "classes"})`;
}
