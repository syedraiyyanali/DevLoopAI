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

export interface WorkspaceMetadata {
  name: string;
  root_path: string;
  total_visible_entries: number;
}

export interface WorkspaceEntry {
  name: string;
  relative_path: string;
  kind: "directory" | "file";
  size_bytes: number | null;
}

export interface WorkspaceListResponse {
  workspace: WorkspaceMetadata;
  relative_path: string;
  entries: WorkspaceEntry[];
}

export interface WorkspaceFileContent {
  workspace: WorkspaceMetadata;
  relative_path: string;
  content: string;
  size_bytes: number;
  truncated: boolean;
}

type ChatStreamEvent =
  | { type: "chunk"; content: string }
  | { type: "done" }
  | { type: "error"; message: string };

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

export async function streamChatMessage(
  message: string,
  onChunk: (chunk: string) => void,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
    method: "POST",
    headers: {
      Accept: "application/x-ndjson",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message }),
  });

  if (!response.ok) {
    throw new ApiError(await getErrorMessage(response), response.status);
  }

  if (!response.body) {
    throw new Error("Streaming response body is unavailable.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();

    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    buffer = processStreamBuffer(buffer, onChunk);
  }

  buffer += decoder.decode();
  processStreamBuffer(buffer, onChunk);
}

function processStreamBuffer(
  buffer: string,
  onChunk: (chunk: string) => void,
): string {
  const lines = buffer.split("\n");
  const remainingBuffer = lines.pop() ?? "";

  for (const line of lines) {
    processStreamLine(line, onChunk);
  }

  return remainingBuffer;
}

function processStreamLine(
  line: string,
  onChunk: (chunk: string) => void,
): void {
  const trimmedLine = line.trim();

  if (!trimmedLine) {
    return;
  }

  const event = JSON.parse(trimmedLine) as ChatStreamEvent;

  if (event.type === "chunk" && event.content) {
    onChunk(event.content);
    return;
  }

  if (event.type === "error") {
    throw new Error(event.message);
  }
}

export async function openWorkspace(path: string): Promise<WorkspaceMetadata> {
  return requestJson<WorkspaceMetadata>("/workspace/open", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ path }),
  });
}

export async function listWorkspace(
  workspacePath: string,
  relativePath = "",
): Promise<WorkspaceListResponse> {
  return requestJson<WorkspaceListResponse>("/workspace/list", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      workspace_path: workspacePath,
      relative_path: relativePath,
    }),
  });
}

export async function readWorkspaceFile(
  workspacePath: string,
  relativePath: string,
): Promise<WorkspaceFileContent> {
  return requestJson<WorkspaceFileContent>("/workspace/read", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      workspace_path: workspacePath,
      relative_path: relativePath,
    }),
  });
}
