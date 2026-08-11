import type { AuditCategory, AuditIntegrityFilter, AuditLedger } from "@fip/contracts";
import { cookies } from "next/headers";

import { getApiUrl, SESSION_COOKIE } from "@/lib/auth/constants";

export interface AuditLedgerFilters {
  category?: AuditCategory;
  integrity?: AuditIntegrityFilter;
  query?: string;
  page?: number;
  pageSize?: number;
}

export async function getAuditLedger(
  filters: AuditLedgerFilters = {},
): Promise<AuditLedger | null> {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return null;
  const parameters = new URLSearchParams();
  if (filters.category) parameters.set("category", filters.category);
  if (filters.integrity && filters.integrity !== "all") {
    parameters.set("integrity", filters.integrity);
  }
  if (filters.query) parameters.set("q", filters.query);
  if (filters.page && filters.page > 1) parameters.set("page", String(filters.page));
  if (filters.pageSize) parameters.set("page_size", String(filters.pageSize));
  const suffix = parameters.size ? `?${parameters.toString()}` : "";
  try {
    const response = await fetch(`${getApiUrl()}/api/v1/audit/ledger${suffix}`, {
      headers: { Authorization: `Bearer ${session}` },
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as AuditLedger;
  } catch {
    return null;
  }
}
