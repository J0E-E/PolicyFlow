import { useEffect, useState } from "react";
import { getHealth, type HealthReport } from "./getHealth.ts";

// Fetches the live /api/health report through the nginx proxy on mount and
// renders loading, error, and success states. Throwaway walking-skeleton proof
// that the SPA -> nginx -> core path works; Epic 5 replaces this content.
export default function HealthStatus() {
  const [healthReport, setHealthReport] = useState<HealthReport | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let isStillMounted = true;
    getHealth()
      .then((report) => {
        if (isStillMounted) {
          setHealthReport(report);
        }
      })
      .catch((error: unknown) => {
        if (isStillMounted) {
          setErrorMessage(
            error instanceof Error ? error.message : "Unknown error",
          );
        }
      })
      .finally(() => {
        if (isStillMounted) {
          setIsLoading(false);
        }
      });
    return () => {
      isStillMounted = false;
    };
  }, []);

  if (isLoading) {
    return <p id="health-loading">Checking API health…</p>;
  }

  if (errorMessage) {
    return (
      <p id="health-error">Could not reach the API: {errorMessage}</p>
    );
  }

  return (
    <div id="health-status">
      <p id="health-overall">
        API status: <span id="health-overall-value">{healthReport?.status}</span>
      </p>
      <p id="health-version">
        Version: <span id="health-version-value">{healthReport?.version}</span>
      </p>
      <ul id="health-checks-list">
        <li id="health-check-db">
          Database: <span id="health-check-db-value">{healthReport?.checks.db}</span>
        </li>
        <li id="health-check-broker">
          Broker: <span id="health-check-broker-value">{healthReport?.checks.broker}</span>
        </li>
      </ul>
    </div>
  );
}
