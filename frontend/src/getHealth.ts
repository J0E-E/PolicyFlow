// Tiny typed fetch helper for the core /api/health endpoint. nginx reverse-
// proxies /api/ to core:8000, so the SPA can call the relative path. This is
// walking-skeleton proof that the proxy works; Epic 5 replaces it.

export interface HealthReport {
  status: string;
  version: string;
  checks: {
    db: string;
    broker: string;
  };
}

export async function getHealth(): Promise<HealthReport> {
  const response = await fetch("/api/health");
  if (!response.ok && response.status !== 503) {
    throw new Error(`Health request failed with status ${response.status}`);
  }
  return (await response.json()) as HealthReport;
}
