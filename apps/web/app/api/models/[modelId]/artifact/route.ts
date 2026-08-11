import { proxyModelArtifact } from "@/lib/models/proxy";

export async function PUT(
  request: Request,
  context: { params: Promise<{ modelId: string }> },
) {
  const { modelId } = await context.params;
  return proxyModelArtifact(
    request,
    `/api/v1/models/${encodeURIComponent(modelId)}/artifact`,
  );
}
