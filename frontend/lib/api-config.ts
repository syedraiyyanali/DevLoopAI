const configuredApiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL?.trim();

if (!configuredApiBaseUrl) {
  throw new Error(
    "NEXT_PUBLIC_API_BASE_URL is missing. Add it to frontend/.env.local.",
  );
}

export const API_BASE_URL = configuredApiBaseUrl.replace(/\/+$/, "");

export const API_DOCS_URL = API_BASE_URL.replace(/\/api\/v\d+$/, "/docs");
