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

export interface WorkspaceDependencySummary {
  manifest: string;
  package_name: string | null;
  dependencies: string[];
  dev_dependencies: string[];
}

export interface WorkspaceGitSummary {
  present: boolean;
  current_branch: string | null;
  remotes: string[];
}

export interface WorkspaceContextSummary {
  workspace: WorkspaceMetadata;
  project_types: string[];
  frameworks: string[];
  important_config_files: string[];
  important_source_directories: string[];
  likely_entry_points: string[];
  detected_languages: Record<string, number>;
  file_count: number;
  directory_count: number;
  dependency_metadata: WorkspaceDependencySummary[];
  git: WorkspaceGitSummary;
  readme_excerpt: string | null;
  ignored_directories: string[];
  warnings: string[];
}

export interface PlannerProjectContext {
  workspace_name: string | null;
  project_types: string[];
  frameworks: string[];
  languages: Record<string, number>;
}

export interface PlannerResponse {
  task_summary: string;
  assumptions: string[];
  detected_project_context: PlannerProjectContext;
  implementation_steps: string[];
  files_likely_to_change: string[];
  tests_verification_required: string[];
  risks: string[];
  dependencies_or_user_input_needed: string[];
  model: string;
  raw_model_response: string | null;
}

export type ReviewRecommendation =
  | "APPROVE"
  | "APPROVE_WITH_CHANGES"
  | "REJECT";

export interface ReviewerResponse {
  overall_assessment: string;
  missing_steps: string[];
  incorrect_assumptions: string[];
  architecture_concerns: string[];
  security_concerns: string[];
  performance_concerns: string[];
  testing_gaps: string[];
  unnecessary_changes: string[];
  recommended_improvements: string[];
  approval_recommendation: ReviewRecommendation;
  model: string;
  raw_model_response: string | null;
}

export type ValidationStatus = "READY" | "READY_WITH_WARNINGS" | "BLOCKED";

export interface ValidatorResponse {
  overall_validation_status: ValidationStatus;
  plan_completeness: string[];
  file_path_validity: string[];
  dependency_concerns: string[];
  environment_tool_requirements: string[];
  security_concerns: string[];
  destructive_operation_warnings: string[];
  missing_user_information: string[];
  test_verification_readiness: string[];
  blockers: string[];
  final_execution_readiness: string;
  model: string;
  raw_model_response: string | null;
}

export interface FinalReviewedPlanSummary {
  final_recommendation: ValidationStatus;
  final_execution_readiness: string;
  execution_ready: boolean;
  required_changes_before_execution: string[];
  blockers: string[];
  warnings: string[];
  risks: string[];
  tests_expected: string[];
  user_approval_required: boolean;
  summary: string;
}

export type ApprovalStatus =
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "REJECTED"
  | "BLOCKED";

export interface PlanningApprovalGate {
  workflow_id: string;
  approval_id: string;
  approval_token: string;
  plan_fingerprint: string;
  status: ApprovalStatus;
  approval_allowed: boolean;
  reason: string;
}

export interface PlanningApprovalActionResponse {
  workflow_id: string;
  approval_id: string;
  plan_fingerprint: string;
  status: ApprovalStatus;
  approval_allowed: boolean;
  message: string;
}

export interface PlanningWorkflowResponse {
  planner_output: PlannerResponse;
  reviewer_output: ReviewerResponse;
  validator_output: ValidatorResponse;
  final_reviewed_summary: FinalReviewedPlanSummary;
  approval: PlanningApprovalGate;
}

export interface PlanningWorkflowHistoryItem {
  workflow_id: string;
  user_task: string;
  workspace_path: string | null;
  plan_fingerprint: string;
  approval_status: ApprovalStatus;
  approval_allowed: boolean;
  approval_reason: string;
  created_at: string;
  updated_at: string;
  approval_decided_at: string | null;
}

export interface PlanningWorkflowHistoryListResponse {
  workflows: PlanningWorkflowHistoryItem[];
}

export interface PlanningWorkflowHistoryRecord
  extends PlanningWorkflowHistoryItem {
  planner_output: PlannerResponse;
  reviewer_output: ReviewerResponse;
  validator_output: ValidatorResponse;
  final_reviewed_summary: FinalReviewedPlanSummary;
}

export type ExecutionPreflightStatus =
  | "READY_FOR_EXECUTION"
  | "REAPPROVAL_REQUIRED"
  | "BLOCKED";

export interface FingerprintVerification {
  stored_fingerprint: string;
  recomputed_fingerprint: string;
  matches: boolean;
}

export interface WorkspacePreflightStatus {
  workspace_path: string | null;
  exists: boolean;
  is_directory: boolean;
  status: string;
}

export interface PreflightFileCheck {
  relative_path: string;
  exists: boolean;
  kind: "file" | "directory" | "missing" | "blocked";
  size_bytes: number | null;
  modified_after_approval: boolean | null;
  note: string;
}

export interface ExecutionPreflightResponse {
  workflow_id: string;
  approval_status: ApprovalStatus;
  status: ExecutionPreflightStatus;
  fingerprint: FingerprintVerification;
  workspace: WorkspacePreflightStatus;
  file_checks: PreflightFileCheck[];
  detected_changes: string[];
  warnings: string[];
  blockers: string[];
  execution_readiness: string;
  reapproval_reason: string | null;
}

export type AllowedOperationType =
  | "read_file"
  | "create_text_file"
  | "modify_text_file"
  | "delete_text_file";

export interface ApprovalMetadata {
  approval_status: ApprovalStatus;
  approved_at: string | null;
  approval_reason: string;
}

export interface RollbackBackupRequirements {
  backup_required: boolean;
  rollback_plan_required: boolean;
  requirements: string[];
}

export interface ExecutionHandoffResponse {
  workflow_id: string;
  approved_plan_fingerprint: string;
  workspace_path: string;
  preflight_result: ExecutionPreflightResponse;
  approved_planned_changes: string[];
  allowed_files: string[];
  allowed_operation_types: AllowedOperationType[];
  expected_tests: string[];
  warnings: string[];
  blockers: string[];
  rollback_backup_requirements: RollbackBackupRequirements;
  user_approval_metadata: ApprovalMetadata;
  execution_allowed: boolean;
  message: string;
}

export interface CoderDryRunOperation {
  operation_type: AllowedOperationType;
  relative_path: string;
  description: string;
  rationale: string;
}

export interface CoderDryRunResponse {
  workflow_id: string;
  approved_plan_fingerprint: string;
  workspace_path: string;
  files_would_modify: string[];
  files_would_create: string[];
  files_would_delete: string[];
  intended_operations: CoderDryRunOperation[];
  proposed_code_change_summary: string;
  dependencies_required: string[];
  tests_to_run: string[];
  rollback_backup_plan: string[];
  warnings: string[];
  blockers: string[];
  model: string;
  execution_performed: boolean;
  mutation_capabilities_enabled: boolean;
  message: string;
}

export interface CoderFileDiffPreview {
  relative_path: string;
  operation_type: AllowedOperationType;
  current_content: string | null;
  proposed_content: string | null;
  unified_diff: string;
  warnings: string[];
}

export interface CoderDiffPreviewResponse {
  workflow_id: string;
  approved_plan_fingerprint: string;
  workspace_path: string;
  file_previews: CoderFileDiffPreview[];
  warnings: string[];
  blockers: string[];
  model: string;
  execution_performed: boolean;
  mutation_capabilities_enabled: boolean;
  message: string;
  review_id: string | null;
  review_fingerprint: string | null;
  reviewed_at: string | null;
}

export type ExecutionStatus =
  | "EXECUTED"
  | "BLOCKED"
  | "REVIEW_STALE"
  | "ROLLED_BACK"
  | "PARTIALLY_FAILED_AND_ROLLED_BACK";

export interface ExecutionFileResult {
  relative_path: string;
  operation_type: "modify_text_file" | "create_text_file";
  status: "CHANGED" | "CREATED" | "ROLLED_BACK" | "NOT_ATTEMPTED" | "FAILED";
  original_content_hash: string | null;
  proposed_content_hash: string;
  final_content_hash: string | null;
  backup_location: string | null;
  backup_status: "CREATED" | "NOT_REQUIRED" | "FAILED";
}

export interface ExecutionApplyResponse {
  execution_id: string;
  workflow_id: string;
  workspace_path: string;
  status: ExecutionStatus;
  files_attempted: string[];
  files_changed: string[];
  file_results: ExecutionFileResult[];
  backup_status: string;
  rollback_available: boolean;
  warnings: string[];
  blockers: string[];
  execution_timestamp: string;
  message: string;
}

export interface ExecutionRollbackResponse {
  execution_id: string;
  workflow_id: string;
  status: "ROLLED_BACK" | "BLOCKED";
  files_restored: string[];
  files_removed: string[];
  warnings: string[];
  blockers: string[];
  rolled_back_at: string | null;
  message: string;
}

export type VerificationStatus =
  | "PASSED"
  | "FAILED"
  | "SKIPPED"
  | "TIMED_OUT"
  | "BLOCKED";

export interface ExecutionVerificationResult {
  verification_id: string;
  execution_id: string;
  workflow_id: string;
  verification_type: string;
  command_identity: string;
  working_directory: string;
  status: VerificationStatus;
  exit_code: number | null;
  duration_seconds: number;
  stdout_excerpt: string;
  stderr_excerpt: string;
  output_truncated: boolean;
  timestamp: string;
  rollback_recommended: boolean;
  changed_files: string[];
  warnings: string[];
  blockers: string[];
}

export interface ExecutionVerificationResponse {
  execution_id: string;
  workflow_id: string;
  results: ExecutionVerificationResult[];
}

export interface ExecutionVerificationHistoryResponse {
  execution_id: string;
  workflow_id: string;
  verifications: ExecutionVerificationResult[];
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

export async function getWorkspaceContext(
  workspacePath: string,
): Promise<WorkspaceContextSummary> {
  return requestJson<WorkspaceContextSummary>("/workspace/context", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      workspace_path: workspacePath,
    }),
  });
}

export async function createPlannerPlan(
  task: string,
  workspacePath?: string,
  constraints: string[] = [],
): Promise<PlannerResponse> {
  return requestJson<PlannerResponse>("/agents/planner", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      task,
      workspace_path: workspacePath || null,
      constraints,
    }),
  });
}

export async function reviewPlannerOutput(
  task: string,
  plannerOutput: PlannerResponse,
  constraints: string[] = [],
): Promise<ReviewerResponse> {
  return requestJson<ReviewerResponse>("/agents/reviewer", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      task,
      planner_output: plannerOutput,
      constraints,
    }),
  });
}

export async function runPlanningWorkflow(
  task: string,
  workspacePath?: string,
  constraints: string[] = [],
): Promise<PlanningWorkflowResponse> {
  return requestJson<PlanningWorkflowResponse>("/workflows/planning", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      task,
      workspace_path: workspacePath || null,
      constraints,
    }),
  });
}

export async function approvePlanningWorkflow(
  approval: PlanningApprovalGate,
): Promise<PlanningApprovalActionResponse> {
  return requestJson<PlanningApprovalActionResponse>("/workflows/planning/approve", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      approval_id: approval.approval_id,
      approval_token: approval.approval_token,
      plan_fingerprint: approval.plan_fingerprint,
    }),
  });
}

export async function rejectPlanningWorkflow(
  approval: PlanningApprovalGate,
): Promise<PlanningApprovalActionResponse> {
  return requestJson<PlanningApprovalActionResponse>("/workflows/planning/reject", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      approval_id: approval.approval_id,
      approval_token: approval.approval_token,
      plan_fingerprint: approval.plan_fingerprint,
    }),
  });
}

export async function listPlanningWorkflowHistory(): Promise<PlanningWorkflowHistoryListResponse> {
  return requestJson<PlanningWorkflowHistoryListResponse>("/workflows/planning");
}

export async function getPlanningWorkflowHistory(
  workflowId: string,
): Promise<PlanningWorkflowHistoryRecord> {
  return requestJson<PlanningWorkflowHistoryRecord>(
    `/workflows/planning/${encodeURIComponent(workflowId)}`,
  );
}

export async function runExecutionPreflight(
  workflowId: string,
): Promise<ExecutionPreflightResponse> {
  return requestJson<ExecutionPreflightResponse>(
    "/workflows/execution/preflight",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        workflow_id: workflowId,
      }),
    },
  );
}

export async function createExecutionHandoff(
  workflowId: string,
): Promise<ExecutionHandoffResponse> {
  return requestJson<ExecutionHandoffResponse>("/workflows/execution/handoff", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      workflow_id: workflowId,
    }),
  });
}

export async function runCoderDryRun(
  handoff: ExecutionHandoffResponse,
): Promise<CoderDryRunResponse> {
  return requestJson<CoderDryRunResponse>("/agents/coder/dry-run", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      handoff,
    }),
  });
}

export async function runCoderDiffPreview(
  dryRun: CoderDryRunResponse,
): Promise<CoderDiffPreviewResponse> {
  return requestJson<CoderDiffPreviewResponse>("/agents/coder/diff-preview", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      dry_run: dryRun,
    }),
  });
}

export async function applyReviewedChanges(
  handoff: ExecutionHandoffResponse,
  dryRun: CoderDryRunResponse,
  diffPreview: CoderDiffPreviewResponse,
): Promise<ExecutionApplyResponse> {
  return requestJson<ExecutionApplyResponse>("/workflows/execution/apply", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      handoff,
      dry_run: dryRun,
      diff_preview: diffPreview,
    }),
  });
}

export async function rollbackExecution(
  executionId: string,
): Promise<ExecutionRollbackResponse> {
  return requestJson<ExecutionRollbackResponse>("/workflows/execution/rollback", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      execution_id: executionId,
    }),
  });
}

export async function runExecutionVerification(
  executionId: string,
  verificationTypes: string[],
): Promise<ExecutionVerificationResponse> {
  return requestJson<ExecutionVerificationResponse>(
    `/workflows/execution/${encodeURIComponent(executionId)}/verify`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        verification_types: verificationTypes,
      }),
    },
  );
}

export async function listExecutionVerifications(
  executionId: string,
): Promise<ExecutionVerificationHistoryResponse> {
  return requestJson<ExecutionVerificationHistoryResponse>(
    `/workflows/execution/${encodeURIComponent(executionId)}/verifications`,
  );
}

export async function validateReviewedPlan(
  task: string,
  plannerOutput: PlannerResponse,
  reviewerOutput: ReviewerResponse,
  constraints: string[] = [],
): Promise<ValidatorResponse> {
  return requestJson<ValidatorResponse>("/agents/validator", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      task,
      planner_output: plannerOutput,
      reviewer_output: reviewerOutput,
      constraints,
    }),
  });
}
