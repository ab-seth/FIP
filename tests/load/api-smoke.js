import http from "k6/http";
import { check, sleep } from "k6";

const baseUrl = (__ENV.BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export const options = {
  stages: [
    { duration: "20s", target: 5 },
    { duration: "40s", target: 10 },
    { duration: "20s", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<2000"],
    checks: ["rate>0.99"],
  },
};

export function setup() {
  const ready = http.get(`${baseUrl}/api/v1/health/ready`);
  check(ready, { "database readiness succeeds": (response) => response.status === 200 });

  if (!__ENV.FIP_LOAD_USERNAME || !__ENV.FIP_LOAD_PASSWORD) {
    return { token: null };
  }
  const login = http.post(
    `${baseUrl}/api/v1/auth/login`,
    JSON.stringify({
      username: __ENV.FIP_LOAD_USERNAME,
      password: __ENV.FIP_LOAD_PASSWORD,
    }),
    { headers: { "Content-Type": "application/json" } },
  );
  check(login, { "load-test account authenticates": (response) => response.status === 200 });
  return { token: login.status === 200 ? login.json("access_token") : null };
}

export default function (data) {
  const health = http.get(`${baseUrl}/health`);
  check(health, { "liveness succeeds": (response) => response.status === 200 });

  if (data.token) {
    const cases = http.get(`${baseUrl}/api/v1/cases`, {
      headers: { Authorization: `Bearer ${data.token}` },
    });
    check(cases, { "authenticated case listing succeeds": (response) => response.status === 200 });
  }
  sleep(1);
}
