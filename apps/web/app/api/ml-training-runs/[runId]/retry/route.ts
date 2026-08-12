import { proxyTrainingRunRetry } from "@/lib/training-runs/proxy";

export async function POST(
  request: Request,
  context: { params: Promise<{ runId: string }> },
) {
  void request;
  const { runId } = await context.params;
  return proxyTrainingRunRetry(runId);
}
