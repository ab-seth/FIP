import { proxyCsvUpload } from "@/lib/transactions/server";

export async function POST(request: Request) {
  return proxyCsvUpload(request, "/api/v1/transactions/upload/validate");
}
