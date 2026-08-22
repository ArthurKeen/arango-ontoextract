/**
 * Theme toggle.
 *
 * The behaviours worth pinning are the ones that break silently: reading the
 * theme the pre-paint script already set (rather than assuming light), writing
 * the attribute the whole palette hangs off, persisting the choice, and not
 * throwing when localStorage is unavailable.
 */

import { render, screen, fireEvent, act } from "@testing-library/react";
import React from "react";
import ThemeToggle, { applyTheme } from "../ThemeToggle";

function setDocumentTheme(theme: string | null) {
  if (theme === null) document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

beforeEach(() => {
  localStorage.clear();
  setDocumentTheme(null);
});

describe("ThemeToggle", () => {
  it("switches the document to dark and remembers it", () => {
    setDocumentTheme("light");
    render(<ThemeToggle />);

    fireEvent.click(screen.getByTestId("theme-toggle"));

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("aoe.theme")).toBe("dark");
  });

  it("switches back to light", () => {
    setDocumentTheme("dark");
    render(<ThemeToggle />);

    fireEvent.click(screen.getByTestId("theme-toggle"));

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem("aoe.theme")).toBe("light");
  });

  it("adopts the theme the pre-paint script already applied", () => {
    // The bootstrap in layout.tsx resolves the theme before React runs. The
    // component must read that, not assume light — otherwise the first click
    // in dark mode would be a no-op that re-applies dark.
    setDocumentTheme("dark");
    render(<ThemeToggle />);

    expect(screen.getByTestId("theme-toggle")).toHaveAttribute(
      "aria-label",
      "Switch to light theme",
    );
  });

  it("labels itself with the mode it would switch to", () => {
    setDocumentTheme("light");
    render(<ThemeToggle />);
    const btn = screen.getByTestId("theme-toggle");
    expect(btn).toHaveAttribute("aria-label", "Switch to dark theme");

    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-label", "Switch to light theme");
  });

  it("treats a missing data-theme as light", () => {
    setDocumentTheme(null);
    render(<ThemeToggle />);

    fireEvent.click(screen.getByTestId("theme-toggle"));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("still applies the theme when localStorage throws", () => {
    // Private browsing: the choice cannot be remembered, but the toggle must
    // not break the page.
    const spy = jest
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new Error("QuotaExceededError");
      });
    setDocumentTheme("light");
    render(<ThemeToggle />);

    expect(() =>
      fireEvent.click(screen.getByTestId("theme-toggle")),
    ).not.toThrow();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    spy.mockRestore();
  });

  it("exposes applyTheme for callers outside the button", () => {
    act(() => applyTheme("dark"));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("aoe.theme")).toBe("dark");
  });

  it("renders a stable icon before mount to avoid a hydration mismatch", () => {
    // Server-rendered markup cannot know the stored choice, so the first paint
    // must match what the server produced regardless of the real theme.
    setDocumentTheme("dark");
    const { container } = render(<ThemeToggle />);
    expect(container.querySelector("span")).toBeInTheDocument();
  });
});
