import { API_BASE_URL } from "./api-config";

export interface BackendHealth {
  status: string;
  service: string;
  version: string;
  environment: string;
}

export interface OllamaModelInfo {
  name: string;
}

export interface OllamaStatus {
  reachable: boolean;
  base_url: string;
  configured_model: string;
  configured_model_available: boolean;
  models: OllamaModelInfo[];
  error: string | null;
}

export interface ChatResponse {
  message: string;
  model: string;
}

interface ApiErrorBody {
  error?: {
    message?: string;
  };
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);

    this.name = "ApiError";
    this.status = status;
  }
}

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as ApiErrorBody;

    if (body.error?.message) {
      return body.error.message;
    }
  } catch {
    return `API request failed with status ${response.status}.`;
  }

  return `API request failed with status ${response.status}.`;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new ApiError(await getErrorMessage(response), response.status);
  }

  return response.json() as Promise<T>;
}

export async function getBackendHealth(): Promise<BackendHealth> {
  return requestJson<BackendHealth>("/health");
}

export async function getOllamaStatus(): Promise<OllamaStatus> {
  return requestJson<OllamaStatus>("/ollama/status");
}

export async function sendChatMessage(message: string): Promise<ChatResponse> {
  return requestJson<ChatResponse>("/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message }),
  });
}
