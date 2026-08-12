import { proxyTrainingArtifact } from "@/lib/training-runs/proxy";

export async function GET(
  request: Request,
  context: {
    params: Promise<{ runId: string; modelKind: string; artifactName: string }>;
  },
) {
  void request;
  const { runId, modelKind, artifactName } = await context.params;
  return proxyTrainingArtifact(runId, modelKind, artifactName);
}
