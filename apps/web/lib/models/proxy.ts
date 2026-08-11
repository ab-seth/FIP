import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { getApiUrl, SESSION_COOKIE } from "@/lib/auth/constants";

const MAX_ARTIFACT_BYTES = 256 * 1024 * 1024;

export async function proxyModelJsonMutation(request: Request, endpoint: string) {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return authenticationRequired();

  let body: string;
  try {
    body = await request.text();
  } catch {
    return NextResponse.json({ detail: "The model request could not be read." }, { status: 400 });
  }

  return forwardModelMutation({
    body,
    contentType: "application/json",
    endpoint,
    method: "POST",
    session,
  });
}

export async function proxyModelArtifact(request: Request, endpoint: string) {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return authenticationRequired();

  const contentLength = request.headers.get("content-length");
  if (
    contentLength &&
    /^\d+$/.test(contentLength) &&
    Number(contentLength) > MAX_ARTIFACT_BYTES
  ) {
    return artifactTooLarge();
  }

  let body: ArrayBuffer;
  try {
    body = await request.arrayBuffer();
  } catch {
    return NextResponse.json({ detail: "The model artifact could not be read." }, { status: 400 });
  }
  if (body.byteLength > MAX_ARTIFACT_BYTES) return artifactTooLarge();

  return forwardModelMutation({
    body,
    contentType: "application/octet-stream",
    endpoint,
    method: "PUT",
    session,
  });
}

async function forwardModelMutation({
  body,
  contentType,
  endpoint,
  method,
  session,
}: {
  body: ArrayBuffer | string;
  contentType: string;
  endpoint: string;
  method: "POST" | "PUT";
  session: string;
}) {
  try {
    const upstream = await fetch(`${getApiUrl()}${endpoint}`, {
      method,
      headers: {
        Authorization: `Bearer ${session}`,
        "Content-Type": contentType,
      },
      body,
      cache: "no-store",
    });
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch {
    return NextResponse.json(
      { detail: "The model operations service is temporarily unavailable." },
      { status: 503 },
    );
  }
}

function authenticationRequired() {
  return NextResponse.json({ detail: "Valid authentication is required" }, { status: 401 });
}

function artifactTooLarge() {
  return NextResponse.json(
    { detail: "The model artifact cannot exceed 256 MB." },
    { status: 413 },
  );
}
