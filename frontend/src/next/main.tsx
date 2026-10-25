import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";
import { AuthGate } from "./app/AuthGate";
import { AppProviders, createQueryClient } from "./app/providers";
import { createAppRouter } from "./app/router";
import "./design/index.css";
import { installGlobalErrorLogging } from "./shared/log/logger";

installGlobalErrorLogging();

const queryClient = createQueryClient();
const router = createAppRouter();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppProviders client={queryClient}>
      <AuthGate>
        <RouterProvider router={router} />
      </AuthGate>
    </AppProviders>
  </StrictMode>,
);
