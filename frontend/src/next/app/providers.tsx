import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { PreferencesProvider } from "../features/settings/preferences";
import { isApiError } from "../shared/api/client";
import { log } from "../shared/log/logger";
import { ConfirmProvider, ToastProvider, TooltipProvider } from "../ui";

/**
 * Query defaults for the whole panel: retry only what can succeed unchanged
 * (network, timeout, 5xx), never mutations; refetch on focus; and log
 * server-side failures. Network failures are shown by the connection banner,
 * not logged once per query.
 */
export function createQueryClient(): QueryClient {
  const logFailure = (kind: string) => (error: unknown) => {
    if (isApiError(error) && error.kind !== "http") return;
    log.warn(`${kind}失败：${error instanceof Error ? error.message : String(error)}`, {
      action: kind,
      detail: isApiError(error) ? { status: error.status, detail: error.detail } : error,
    });
  };
  return new QueryClient({
    queryCache: new QueryCache({ onError: logFailure("query") }),
    mutationCache: new MutationCache({ onError: logFailure("mutation") }),
    defaultOptions: {
      queries: {
        staleTime: 2_000,
        refetchOnWindowFocus: true,
        retry: (count, error) => isApiError(error) && error.retryable && count < 2,
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
      },
      mutations: { retry: false },
    },
  });
}

export function AppProviders({ client, children }: { client: QueryClient; children: ReactNode }) {
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider delayDuration={400}>
        <ToastProvider>
          <ConfirmProvider>
            <PreferencesProvider>{children}</PreferencesProvider>
          </ConfirmProvider>
        </ToastProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
