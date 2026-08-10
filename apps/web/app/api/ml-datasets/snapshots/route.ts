import { proxyDatasetMutation } from "@/lib/ml-datasets/proxy";

export async function POST(request: Request) {
  return proxyDatasetMutation(request, "/api/v1/ml/datasets/snapshots");
}
