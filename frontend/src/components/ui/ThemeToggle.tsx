"use client";

/**
 * Light/dark theme toggle.
 *
 * Sits in every dashboard header; flipping it re-skins the whole app, because
 * the themes are two palettes over one set of CSS variables (see
 * `app/globals.css`) rather than per-component `dark:` variants.
 *
 * The initial value is resolved by the pre-paint script in `layout.tsx`, not
 * here — this component only *reads* what the document already says, so there
 * is no flash and no hydration mismatch on the attribute itself.
 *
 * The workspace canvas is deliberately exempt: it pins itself to the light
 * token set and paints its own dark chrome, so a graph tuned for a dark canvas
 * stays on a dark canvas in both themes.
 */

import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "aoe.theme";

function readTheme(): Theme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.getAttribute("data-theme") === "dark"
    ? "dark"
    : "light";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Private browsing / storage disabled — the theme still applies for this
    // page load, it just will not be remembered.
  }
}

export default function ThemeToggle({ className = "" }: { className?: string }) {
  // Start light and correct on mount: the server cannot know the stored choice,
  // so rendering the real value directly would be a hydration mismatch.
  const [theme, setTheme] = useState<Theme>("light");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setTheme(readTheme());
    setMounted(true);
  }, []);

  const toggle = useCallback(() => {
    const next: Theme = readTheme() === "dark" ? "light" : "dark";
    applyTheme(next);
    setTheme(next);
  }, []);

  const goingDark = theme === "light";
  const label = goingDark ? "Switch to dark theme" : "Switch to light theme";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title="Switch between light and dark mode. Your choice is remembered on this device."
      data-testid="theme-toggle"
      className={`inline-flex h-8 w-8 items-center justify-center rounded-lg border border-gray-300 text-gray-600 transition-colors hover:border-blue-600 hover:text-blue-600 ${className}`}
    >
      {/* Show the icon for the mode you would switch TO. Hidden from a11y —
          the button already carries a label. Before mount, render the light-mode
          icon so server and client markup agree. */}
      <span aria-hidden="true" className="text-sm leading-none">
        {mounted && !goingDark ? "☀" : "☾"}
      </span>
    </button>
  );
}
