import { proxyCaseMutation } from "@/lib/cases/proxy";

export async function POST(
  request: Request,
  context: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await context.params;
  return proxyCaseMutation(request, `/api/v1/cases/${encodeURIComponent(caseId)}/review`);
}
