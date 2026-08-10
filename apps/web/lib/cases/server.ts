import type { CaseDetail, CaseSummary } from "@fip/contracts";
import { cookies } from "next/headers";

import { getApiUrl, SESSION_COOKIE } from "@/lib/auth/constants";

export async function getCases(): Promise<CaseSummary[]> {
  return (await caseRequest("/api/v1/cases")) ?? [];
}

export async function getCase(caseId: string): Promise<CaseDetail | null> {
  return caseRequest(`/api/v1/cases/${encodeURIComponent(caseId)}`);
}

async function caseRequest<T>(path: string): Promise<T | null> {
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
