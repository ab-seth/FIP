import { proxyModelJsonMutation } from "@/lib/models/proxy";

export async function POST(request: Request) {
  return proxyModelJsonMutation(request, "/api/v1/models");
}
