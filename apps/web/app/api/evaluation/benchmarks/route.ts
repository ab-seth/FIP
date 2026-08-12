import { proxyBenchmarkCreation } from "@/lib/benchmarks/proxy";

export async function POST(request: Request) {
  return proxyBenchmarkCreation(request);
}
