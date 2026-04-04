/**
 * Centralized access to public environment variables (NEXT_PUBLIC_*).
 */
export const publicEnv = {
  apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
} as const;
