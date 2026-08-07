export const SESSION_COOKIE = "fip_session";

export function getApiUrl() {
  return (process.env.FIP_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

export function isSecureSessionCookie() {
  if (process.env.FIP_COOKIE_SECURE === "false") {
    return false;
  }
  return process.env.FIP_COOKIE_SECURE === "true" || process.env.NODE_ENV === "production";
}
