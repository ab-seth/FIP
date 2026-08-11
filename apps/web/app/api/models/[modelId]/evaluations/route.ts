import { proxyModelJsonMutation } from "@/lib/models/proxy";

export async function POST(
  request: Request,
  context: { params: Promise<{ modelId: string }> },
) {
  const { modelId } = await context.params;
  return proxyModelJsonMutation(
    request,
    `/api/v1/models/${encodeURIComponent(modelId)}/evaluations`,
  );
}
