import { apiRequest } from "./client";

/**
 * Compatibility auth API helper module referenced by documentation.
 * Uses the shared typed API client.
 */
export async function getAuthMe() {
  return apiRequest("/api/v1/auth/me");
}
