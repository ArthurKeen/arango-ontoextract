/**
 * The workspace subtree opts out of light/dark theming (globals.css
 * ``[data-canvas-chrome]``). These tests pin the declarations that make that
 * opt-out actually work, because getting them wrong is invisible in light mode
 * and only shows up as unreadable text in dark mode.
 */

import fs from "fs";
import path from "path";

const CSS = fs.readFileSync(path.join(__dirname, "..", "globals.css"), "utf8");

function canvasChromeBlock(): string {
  const start = CSS.indexOf("[data-canvas-chrome] {");
  expect(start).toBeGreaterThan(-1);
  const end = CSS.indexOf("\n}", start);
  return CSS.slice(start, end);
}

describe("[data-canvas-chrome]", () => {
  it("hints the light UA colour scheme", () => {
    // Not `dark`, despite the canvas being dark: the floating panels in this
    // subtree are white.
    expect(canvasChromeBlock()).toMatch(/color-scheme:\s*light\s*;/);
  });

  it("also declares an explicit colour, which color-scheme cannot supply", () => {
    // `color-scheme` only provides the UA default for an element with no
    // colour of its own. In dark theme `html` resolves its colour to white and
    // `body` inherits it, so this subtree inherits white too -- an inherited
    // value counts as having one, and the `light` hint is never consulted.
    // Without this line every element in here that relies on inheritance
    // renders white on the white panels; the Create-Ontology dialog's inputs
    // were invisible exactly this way.
    expect(canvasChromeBlock()).toMatch(/^\s*color:\s*#000\s*;/m);
  });

  it("restores the light neutral tokens so utilities keep their contrast", () => {
    const block = canvasChromeBlock();
    expect(block).toMatch(/--color-white:\s*#fff\s*;/);
    expect(block).toMatch(/--color-gray-900:/);
  });
});
