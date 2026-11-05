import { describe, expect, it } from "vitest";
import { pinnedFirst } from "./pins";

describe("pinnedFirst", () => {
  const items = [{ id: "a" }, { id: "b" }, { id: "c" }];
  it("moves pinned ones to the front and keeps the rest in order", () => {
    expect(pinnedFirst(items, new Set(["c"])).map((i) => i.id)).toEqual(["c", "a", "b"]);
  });
  it("leaves the list alone when nothing is pinned", () => {
    expect(pinnedFirst(items, new Set())).toBe(items);
  });
});
