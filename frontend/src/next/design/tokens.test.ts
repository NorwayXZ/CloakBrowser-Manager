// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// Vitest blanks CSS imports, so read the file itself.
const css = readFileSync(fileURLToPath(new URL("./tokens.css", import.meta.url)), "utf8");

// Contrast of the text / background pairs the components actually use, in
// both themes. 4.5:1 for text, 3:1 for control boundaries (WCAG 1.4.3, 1.4.11).

function block(selector: string): Record<string, [number, number, number]> {
  const start = css.indexOf(`${selector} {`);
  const body = css.slice(start, css.indexOf("}", start));
  const tokens: Record<string, [number, number, number]> = {};
  for (const match of body.matchAll(/--c-([a-z0-9-]+):\s*(\d+)\s+(\d+)\s+(\d+);/g)) {
    tokens[match[1]!] = [Number(match[2]), Number(match[3]), Number(match[4])];
  }
  return tokens;
}

const light = block(":root");
const dark = { ...light, ...block(':root[data-theme="dark"]') };

function luminance([r, g, b]: [number, number, number]) {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function contrast(a: [number, number, number], b: [number, number, number]) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const TEXT_PAIRS: [string, string][] = [
  ["fg", "canvas"],
  ["fg", "surface"],
  ["fg", "surface-2"],
  ["fg", "accent-soft"],
  ["fg-2", "canvas"],
  ["fg-2", "surface"],
  ["fg-2", "surface-2"],
  ["fg-3", "canvas"],
  ["fg-3", "surface"],
  ["canvas", "fg"], // tooltip
  ["accent", "surface"],
  ["accent", "canvas"],
  ["accent", "accent-soft"],
  ["on-accent", "accent"],
  ["on-accent", "accent-hover"],
  ["on-danger", "danger"],
  ["on-danger", "danger-hover"],
  ["danger", "surface"],
  ["success", "surface"],
  ["success", "success-soft"],
  ["warning", "warning-soft"],
  ["danger", "danger-soft"],
  ["info", "info-soft"],
];

const BOUNDARY_PAIRS: [string, string][] = [
  ["border-strong", "surface"],
  ["border-strong", "canvas"],
  ["accent", "surface"], // focus ring
  ["fg-3", "surface"], // stopped status dot
];

describe.each([
  ["light", light],
  ["dark", dark],
])("%s theme", (_name, tokens) => {
  it.each(TEXT_PAIRS)("%s on %s reaches 4.5:1", (fg, bg) => {
    expect(tokens[fg], fg).toBeDefined();
    expect(tokens[bg], bg).toBeDefined();
    expect(contrast(tokens[fg]!, tokens[bg]!)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(BOUNDARY_PAIRS)("%s against %s reaches 3:1", (fg, bg) => {
    expect(contrast(tokens[fg]!, tokens[bg]!)).toBeGreaterThanOrEqual(3);
  });
});

it("defines every light token again for dark", () => {
  expect(Object.keys(block(':root[data-theme="dark"]')).sort()).toEqual(Object.keys(light).sort());
});
