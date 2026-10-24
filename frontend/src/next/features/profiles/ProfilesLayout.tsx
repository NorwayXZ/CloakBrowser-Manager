import { Outlet } from "react-router";
import { LaunchProvider } from "./launch";

/** Every environment page shares one launch flow (preflight dialog, busy state). */
export function ProfilesLayout() {
  return (
    <LaunchProvider>
      <Outlet />
    </LaunchProvider>
  );
}
