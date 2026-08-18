import { describe, expect, it } from "vitest";
import { shouldEnterProfileViewer } from "./launchNavigation";

describe("shouldEnterProfileViewer", () => {
  it("opens the embedded viewer for one VNC launch", () => {
    expect(shouldEnterProfileViewer("vnc", 1)).toBe(true);
  });

  it("keeps the environment list visible for a native browser window", () => {
    expect(shouldEnterProfileViewer("native-window", 1)).toBe(false);
  });

  it("keeps the environment list visible after a batch launch", () => {
    expect(shouldEnterProfileViewer("vnc", 2)).toBe(false);
    expect(shouldEnterProfileViewer("native-window", 2)).toBe(false);
  });
});
