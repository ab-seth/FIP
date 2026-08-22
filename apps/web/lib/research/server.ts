import type { ResearchModelEvidence } from "@fip/contracts";
import { cookies } from "next/headers";

import { getApiUrl, SESSION_COOKIE } from "@/lib/auth/constants";

export async function getResearchModelEvidence(): Promise<ResearchModelEvidence | null> {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return null;

  try {
    const response = await fetch(`${getApiUrl()}/api/v1/ml/research-evidence`, {
      headers: { Authorization: `Bearer ${session}` },
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as ResearchModelEvidence;
  } catch {
    return null;
  }
}
