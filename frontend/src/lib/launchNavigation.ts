import type { ViewerMode } from "./api";

export function shouldEnterProfileViewer(viewerMode: ViewerMode, launchCount: number) {
  return launchCount === 1 && viewerMode === "vnc";
}
