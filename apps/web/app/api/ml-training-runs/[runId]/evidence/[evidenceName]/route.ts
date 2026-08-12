import { proxyTrainingEvidence } from "@/lib/training-runs/proxy";

export async function GET(
  request: Request,
  context: { params: Promise<{ runId: string; evidenceName: string }> },
) {
  void request;
  const { runId, evidenceName } = await context.params;
  return proxyTrainingEvidence(runId, evidenceName);
}
