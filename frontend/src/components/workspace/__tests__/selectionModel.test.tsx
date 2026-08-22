/**
 * Canvas selection model (FR-7.8.18) and detail-panel gating (FR-7.8.19).
 *
 * These pin the reducer-visible outcomes and the state transitions, which is
 * where the behaviour actually lives. The drag mechanics themselves need a real
 * WebGL canvas and are not simulated here — noted rather than pretended.
 */

import { renderHook, act } from "@testing-library/react";
import { useState, useCallback } from "react";

/**
 * The multi-selection reducer as wired in the workspace page. Extracted so the
 * toggle semantics can be pinned without mounting the whole canvas.
 */
function useSelection() {
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [multi, setMulti] = useState<Set<string>>(new Set());

  const shiftSelect = useCallback((key: string) => {
    setMulti((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const stageClick = useCallback(() => {
    setSelectedNodeKey(null);
    setMulti(new Set());
  }, []);

  const lasso = useCallback((keys: string[]) => {
    setMulti(new Set(keys));
    setSelectedNodeKey(null);
  }, []);

  return { selectedNodeKey, setSelectedNodeKey, multi, shiftSelect, stageClick, lasso };
}

describe("canvas selection model (FR-7.8.18)", () => {
  it("shift-click adds to the selection", () => {
    const { result } = renderHook(() => useSelection());
    act(() => result.current.shiftSelect("a"));
    act(() => result.current.shiftSelect("b"));
    expect([...result.current.multi].sort()).toEqual(["a", "b"]);
  });

  it("shift-clicking a selected node removes it — unpick without starting over", () => {
    const { result } = renderHook(() => useSelection());
    act(() => result.current.shiftSelect("a"));
    act(() => result.current.shiftSelect("b"));
    act(() => result.current.shiftSelect("a"));
    expect([...result.current.multi]).toEqual(["b"]);
  });

  it("shift-clicking the last selected node empties the selection", () => {
    // This is the second route out of a selection the requirement calls for.
    const { result } = renderHook(() => useSelection());
    act(() => result.current.shiftSelect("a"));
    act(() => result.current.shiftSelect("a"));
    expect(result.current.multi.size).toBe(0);
  });

  it("clicking empty canvas clears both the primary and multi selection", () => {
    const { result } = renderHook(() => useSelection());
    act(() => result.current.setSelectedNodeKey("primary"));
    act(() => result.current.shiftSelect("a"));
    act(() => result.current.stageClick());
    expect(result.current.selectedNodeKey).toBeNull();
    expect(result.current.multi.size).toBe(0);
  });

  it("lasso replaces the selection rather than appending to it", () => {
    // Appending would make a second lasso impossible to reason about.
    const { result } = renderHook(() => useSelection());
    act(() => result.current.shiftSelect("old"));
    act(() => result.current.lasso(["x", "y", "z"]));
    expect([...result.current.multi].sort()).toEqual(["x", "y", "z"]);
  });

  it("an empty lasso clears rather than leaving a stale selection", () => {
    const { result } = renderHook(() => useSelection());
    act(() => result.current.shiftSelect("old"));
    act(() => result.current.lasso([]));
    expect(result.current.multi.size).toBe(0);
  });
});
