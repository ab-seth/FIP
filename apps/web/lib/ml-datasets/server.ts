import type { DatasetReadiness, OperationalDatasetSummary } from "@fip/contracts";
import { cookies } from "next/headers";

import { getApiUrl, SESSION_COOKIE } from "@/lib/auth/constants";

export async function getDatasetReadiness(): Promise<DatasetReadiness | null> {
  return datasetRequest("/api/v1/ml/datasets/readiness");
}

export async function getOperationalDatasets(): Promise<OperationalDatasetSummary[]> {
  return (await datasetRequest("/api/v1/ml/datasets")) ?? [];
}

async function datasetRequest<T>(path: string): Promise<T | null> {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return null;
  try {
    const response = await fetch(`${getApiUrl()}${path}`, {
      headers: { Authorization: `Bearer ${session}` },
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}
