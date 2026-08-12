import { proxyTrainingRunCreation } from "@/lib/training-runs/proxy";

export async function POST(request: Request) {
  return proxyTrainingRunCreation(request);
}
