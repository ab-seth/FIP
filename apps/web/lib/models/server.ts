import type {
  ModelArtifactStatus,
  RegisteredModel,
  ShadowEvaluationReport,
} from "@fip/contracts";
import { cookies } from "next/headers";

import { getApiUrl, SESSION_COOKIE } from "@/lib/auth/constants";

export async function getRegisteredModels(): Promise<RegisteredModel[] | null> {
  return modelRequest("/api/v1/models");
}

export async function getModelArtifactStatus(
  modelId: string,
): Promise<ModelArtifactStatus | null> {
  return modelRequest(`/api/v1/models/${encodeURIComponent(modelId)}/artifact`);
}

export async function getModelEvaluations(modelId: string): Promise<ShadowEvaluationReport[]> {
  return (
    (await modelRequest(`/api/v1/models/${encodeURIComponent(modelId)}/evaluations`)) ?? []
  );
}

async function modelRequest<T>(path: string): Promise<T | null> {
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
