import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { getApiUrl, SESSION_COOKIE } from "@/lib/auth/constants";

export async function proxyTrainingRunCreation(request: Request) {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return authenticationRequired();
  let body: string;
  try {
    body = await request.text();
  } catch {
    return NextResponse.json({ detail: "The training request could not be read." }, { status: 400 });
  }
  return forward({
    endpoint: "/api/v1/ml/training-runs",
    session,
    method: "POST",
    body,
  });
}

export async function proxyTrainingRunRetry(runId: string) {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return authenticationRequired();
  return forward({
    endpoint: `/api/v1/ml/training-runs/${encodeURIComponent(runId)}/retry`,
    session,
    method: "POST",
    body: "{}",
  });
}

export async function proxyTrainingArtifact(
  runId: string,
  modelKind: string,
  artifactName: string,
) {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return authenticationRequired();
  const endpoint = [
    "/api/v1/ml/training-runs",
    encodeURIComponent(runId),
    "artifacts",
    encodeURIComponent(modelKind),
    encodeURIComponent(artifactName),
  ].join("/");
  return forward({ endpoint, session, method: "GET" });
}

export async function proxyTrainingEvidence(runId: string, evidenceName: string) {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return authenticationRequired();
  const endpoint = [
    "/api/v1/ml/training-runs",
    encodeURIComponent(runId),
    "evidence",
    encodeURIComponent(evidenceName),
  ].join("/");
  return forward({ endpoint, session, method: "GET" });
}

async function forward({
  body,
  endpoint,
  method,
  session,
}: {
  body?: string;
  endpoint: string;
  method: "GET" | "POST";
  session: string;
}) {
  try {
    const upstream = await fetch(`${getApiUrl()}${endpoint}`, {
      method,
      headers: {
        Authorization: `Bearer ${session}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body,
      cache: "no-store",
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Disposition": upstream.headers.get("Content-Disposition") ?? "inline",
        "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch {
    return NextResponse.json(
      { detail: "The training operations service is temporarily unavailable." },
      { status: 503 },
    );
  }
}

function authenticationRequired() {
  return NextResponse.json({ detail: "Valid authentication is required" }, { status: 401 });
}
