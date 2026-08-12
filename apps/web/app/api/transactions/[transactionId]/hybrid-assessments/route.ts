import { proxyHybridMutation } from "@/lib/hybrid/proxy";

export async function POST(
  request: Request,
  context: { params: Promise<{ transactionId: string }> },
) {
  const { transactionId } = await context.params;
  return proxyHybridMutation(request, transactionId);
}
