"use client";

import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  applyTaskExecution,
  applyReviewedChanges,
  commitVerifiedExecution,
  continueAutonomousTask,
  createExecutionHandoff,
  getAutonomousTask,
  getExecutionHistoryDetail,
  getExecutionQuality,
  getGitStatus,
  getPlanningWorkflowHistory,
  getTaskExecution,
  listExecutionVerifications,
  listExecutionHistory,
  listPlanningWorkflowHistory,
  rollbackExecution,
  rollbackTaskExecution,
  retryTaskExecution,
  runCoderDiffPreview,
  runCoderDryRun,
  runExecutionPreflight,
  runExecutionVerification,
  startAutonomousTask,
  prepareTaskExecution,
  verifyTaskExecution,
  type AutonomousTaskSession,
  type CoderDiffPreviewResponse,
  type CoderDryRunResponse,
  type ExecutionApplyResponse,
  type ExecutionHandoffResponse,
  type ExecutionHistoryDetail,
  type ExecutionHistoryItem,
  type ExecutionPreflightResponse,
  type ExecutionQualityResponse,
  type ExecutionRollbackResponse,
  type ExecutionVerificationResult,
  type GitStatusResponse,
  type GitCommitResponse,
  type PlanningWorkflowHistoryItem,
  type PlanningWorkflowHistoryRecord,
  type TaskExecutionSession,
} from "../lib/api-client";

type LoadingAction =
  | "history"
  | "workflow"
  | "preflight"
  | "handoff"
  | "dry-run"
  | "diff"
  | "apply"
  | "verify"
  | "rollback"
  | "task-prepare"
  | "task-apply"
  | "task-verify"
  | "task-rollback"
  | "task-retry"
  | "autonomous-start"
  | "autonomous-continue"
  | "autonomous-load"
  | "git-status"
  | "git-commit"
  | null;

const SERVER_ALLOWED_VERIFICATIONS = [
  "python_compile",
  "pytest",
  "frontend_lint",
  "frontend_build",
];

export default function ExecutionReviewPanel() {
  const [workflows, setWorkflows] = useState<PlanningWorkflowHistoryItem[]>([]);
  const [selectedWorkflow, setSelectedWorkflow] =
    useState<PlanningWorkflowHistoryRecord | null>(null);
  const [preflight, setPreflight] = useState<ExecutionPreflightResponse | null>(null);
  const [handoff, setHandoff] = useState<ExecutionHandoffResponse | null>(null);
  const [dryRun, setDryRun] = useState<CoderDryRunResponse | null>(null);
  const [diffPreview, setDiffPreview] = useState<CoderDiffPreviewResponse | null>(null);
  const [execution, setExecution] = useState<ExecutionApplyResponse | null>(null);
  const [rollback, setRollback] = useState<ExecutionRollbackResponse | null>(null);
  const [verificationTypes, setVerificationTypes] = useState<string[]>(["python_compile"]);
  const [verifications, setVerifications] = useState<ExecutionVerificationResult[]>([]);
  const [executions, setExecutions] = useState<ExecutionHistoryItem[]>([]);
  const [selectedExecution, setSelectedExecution] = useState<ExecutionHistoryDetail | null>(null);
  const [selectedExecutionQuality, setSelectedExecutionQuality] =
    useState<ExecutionQualityResponse | null>(null);
  const [executionHistoryLoading, setExecutionHistoryLoading] = useState(false);
  const [executionHistoryError, setExecutionHistoryError] = useState("");
  const [taskExecution, setTaskExecution] = useState<TaskExecutionSession | null>(null);
  const [taskExecutionIdInput, setTaskExecutionIdInput] = useState("");
  const [autonomousTask, setAutonomousTask] = useState<AutonomousTaskSession | null>(null);
  const [autonomousTaskText, setAutonomousTaskText] = useState("");
  const [autonomousWorkspacePath, setAutonomousWorkspacePath] = useState("");
  const [autonomousSessionIdInput, setAutonomousSessionIdInput] = useState("");
  const [gitStatus, setGitStatus] = useState<GitStatusResponse | null>(null);
  const [gitCommit, setGitCommit] = useState<GitCommitResponse | null>(null);
  const [gitCommitMessage, setGitCommitMessage] = useState("");
  const [loadingAction, setLoadingAction] = useState<LoadingAction>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void loadHistory();
    void loadExecutionHistory();
  }, []);

  const selectedWorkflowId = selectedWorkflow?.workflow_id ?? "";
  const canRunPreflight = Boolean(selectedWorkflow) && loadingAction === null;
  const canCreateHandoff =
    preflight?.status === "READY_FOR_EXECUTION" && loadingAction === null;
  const canRunDryRun = Boolean(handoff) && loadingAction === null;
  const canRunDiff = Boolean(dryRun) && loadingAction === null;
  const hasCurrentDiffReview = Boolean(
    diffPreview?.review_id && diffPreview.review_fingerprint && diffPreview.reviewed_at,
  );
  const canApply =
    selectedWorkflow?.approval_status === "APPROVED" &&
    preflight?.status === "READY_FOR_EXECUTION" &&
    Boolean(handoff?.execution_allowed) &&
    Boolean(dryRun) &&
    hasCurrentDiffReview &&
    !execution &&
    loadingAction === null;
  const executionRolledBack = rollback?.status === "ROLLED_BACK" || execution?.status === "ROLLED_BACK";
  const canVerify =
    execution?.status === "EXECUTED" &&
    !executionRolledBack &&
    verificationTypes.length > 0 &&
    loadingAction === null;
  const canRollback =
    execution?.status === "EXECUTED" &&
    execution.rollback_available &&
    !executionRolledBack &&
    loadingAction === null;
  const progress = useMemo(
    () => [
      { label: "Planning", active: Boolean(selectedWorkflow), state: selectedWorkflow ? "ready" : "waiting" },
      { label: "Approval", active: selectedWorkflow?.approval_status === "APPROVED", state: selectedWorkflow?.approval_status ?? "waiting" },
      { label: "Preflight", active: preflight?.status === "READY_FOR_EXECUTION", state: preflight?.status ?? "waiting" },
      { label: "Handoff", active: Boolean(handoff), state: handoff ? "ready" : "waiting" },
      { label: "Dry Run", active: Boolean(dryRun), state: dryRun ? "ready" : "waiting" },
      { label: "Diff", active: Boolean(diffPreview), state: diffPreview ? "ready" : "waiting" },
      { label: "Apply", active: execution?.status === "EXECUTED", state: execution?.status ?? "waiting" },
      {
        label: "Verify",
        active: verifications.some((verification) => verification.status === "PASSED"),
        state: latestVerificationState(verifications),
      },
      { label: "Rollback", active: executionRolledBack, state: rollback?.status ?? "conditional" },
    ],
    [diffPreview, dryRun, execution, executionRolledBack, handoff, preflight, rollback, selectedWorkflow, verifications],
  );

  async function loadHistory() {
    setLoadingAction("history");
    setError("");

    try {
      const result = await listPlanningWorkflowHistory();
      setWorkflows(result.workflows);
    } catch (loadError: unknown) {
      setError(getErrorMessage(loadError, "Unable to load workflow history."));
    } finally {
      setLoadingAction(null);
    }
  }

  async function loadExecutionHistory() {
    setExecutionHistoryLoading(true);
    setExecutionHistoryError("");

    try {
      const result = await listExecutionHistory();
      setExecutions(result.executions);
    } catch (loadError: unknown) {
      setExecutionHistoryError(
        getErrorMessage(loadError, "Unable to load execution history."),
      );
    } finally {
      setExecutionHistoryLoading(false);
    }
  }

  async function selectExecution(executionId: string) {
    setExecutionHistoryLoading(true);
    setExecutionHistoryError("");

    try {
      const [detail, quality] = await Promise.all([
        getExecutionHistoryDetail(executionId),
        getExecutionQuality(executionId),
      ]);
      setSelectedExecution(detail);
      setSelectedExecutionQuality(quality);
    } catch (loadError: unknown) {
      setExecutionHistoryError(
        getErrorMessage(loadError, "Unable to load execution detail."),
      );
    } finally {
      setExecutionHistoryLoading(false);
    }
  }

  async function prepareSelectedTask() {
    if (!selectedWorkflow) {
      return;
    }

    await runStep(
      "task-prepare",
      () => prepareTaskExecution(selectedWorkflow.workflow_id),
      (result) => setTaskExecution(result),
    );
  }

  async function loadTaskExecution() {
    if (!taskExecutionIdInput.trim()) {
      return;
    }

    await runStep(
      "task-prepare",
      () => getTaskExecution(taskExecutionIdInput.trim()),
      (result) => setTaskExecution(result),
    );
  }

  async function applyPreparedTask() {
    if (!taskExecution) {
      return;
    }

    const confirmed = window.confirm(
      `Apply reviewed changes for task session ${taskExecution.task_execution_id}?\n\nThis will modify project files using the persisted reviewed diff.`,
    );
    if (!confirmed) {
      return;
    }

    await runStep(
      "task-apply",
      () => applyTaskExecution(taskExecution.task_execution_id, taskExecution.state),
      (result) => {
        setTaskExecution(result);
        void loadExecutionHistory();
        if (result.mutation_execution_id) {
          void selectExecution(result.mutation_execution_id);
        }
      },
    );
  }

  async function verifyAppliedTask() {
    if (!taskExecution) {
      return;
    }

    await runStep(
      "task-verify",
      () => verifyTaskExecution(taskExecution.task_execution_id, taskExecution.state),
      (result) => {
        setTaskExecution(result);
        void loadExecutionHistory();
        if (result.mutation_execution_id) {
          void selectExecution(result.mutation_execution_id);
        }
      },
    );
  }

  async function rollbackTask() {
    if (!taskExecution) {
      return;
    }

    const confirmed = window.confirm(
      `Rollback task session ${taskExecution.task_execution_id}?\n\nRollback remains explicit and uses the persisted execution snapshot.`,
    );
    if (!confirmed) {
      return;
    }

    await runStep(
      "task-rollback",
      () => rollbackTaskExecution(taskExecution.task_execution_id, taskExecution.state),
      (result) => {
        setTaskExecution(result);
        void loadExecutionHistory();
        if (result.mutation_execution_id) {
          void selectExecution(result.mutation_execution_id);
        }
      },
    );
  }

  async function retryFailedTask() {
    if (!taskExecution) {
      return;
    }

    await runStep(
      "task-retry",
      () => retryTaskExecution(taskExecution.task_execution_id, taskExecution.state),
      (result) => setTaskExecution(result),
    );
  }

  async function startAutonomousSession() {
    if (!autonomousTaskText.trim()) {
      return;
    }

    await runStep(
      "autonomous-start",
      () => startAutonomousTask(autonomousTaskText.trim(), autonomousWorkspacePath),
      (result) => {
        setAutonomousTask(result);
        setAutonomousSessionIdInput(result.autonomous_session_id);
        void loadHistory();
      },
    );
  }

  async function loadAutonomousSession() {
    if (!autonomousSessionIdInput.trim()) {
      return;
    }

    await runStep(
      "autonomous-load",
      () => getAutonomousTask(autonomousSessionIdInput.trim()),
      (result) => setAutonomousTask(result),
    );
  }

  async function continueAutonomousSession() {
    if (!autonomousTask) {
      return;
    }

    await runStep(
      "autonomous-continue",
      () => continueAutonomousTask(autonomousTask.autonomous_session_id, autonomousTask.state),
      (result) => {
        setAutonomousTask(result);
        if (result.task_execution) {
          setTaskExecution(result.task_execution);
        }
        void loadHistory();
        void loadExecutionHistory();
      },
    );
  }

  async function loadGitStatus() {
    const workspacePath =
      selectedExecution?.workspace_path ??
      taskExecution?.workspace_path ??
      selectedWorkflow?.workspace_path ??
      "";
    if (!workspacePath) {
      setError("Select a workflow or execution with a workspace path before reading Git status.");
      return;
    }

    await runStep(
      "git-status",
      () => getGitStatus(workspacePath, selectedExecution?.execution_id ?? taskExecution?.mutation_execution_id),
      (result) => setGitStatus(result),
    );
  }

  async function commitSelectedExecution() {
    const executionId = selectedExecution?.execution_id ?? taskExecution?.mutation_execution_id;
    if (!executionId) {
      setError("Select a quality-passed execution before committing.");
      return;
    }

    const confirmed = window.confirm(
      `Commit verified changes for execution ${executionId}?\n\nOnly audited execution paths will be staged. This will not push.`,
    );
    if (!confirmed) {
      return;
    }

    await runStep(
      "git-commit",
      () => commitVerifiedExecution(executionId, gitCommitMessage),
      (result) => {
        setGitCommit(result);
        void loadGitStatus();
      },
    );
  }

  async function selectWorkflow(workflowId: string) {
    setLoadingAction("workflow");
    setError("");
    resetExecutionState();

    try {
      setSelectedWorkflow(await getPlanningWorkflowHistory(workflowId));
    } catch (loadError: unknown) {
      setError(getErrorMessage(loadError, "Unable to open workflow."));
    } finally {
      setLoadingAction(null);
    }
  }

  async function runStep<T>(
    action: Exclude<LoadingAction, "history" | "workflow" | null>,
    callback: () => Promise<T>,
    applyResult: (result: T) => void,
  ) {
    setLoadingAction(action);
    setError("");

    try {
      applyResult(await callback());
    } catch (stepError: unknown) {
      setError(getErrorMessage(stepError, "Execution review step failed."));
    } finally {
      setLoadingAction(null);
    }
  }

  function resetExecutionState() {
    setPreflight(null);
    setHandoff(null);
    setDryRun(null);
    setDiffPreview(null);
    resetMutationState();
  }

  function resetMutationState() {
    setExecution(null);
    setRollback(null);
    setVerifications([]);
  }

  function resetAfterPreflight(result: ExecutionPreflightResponse) {
    setPreflight(result);
    setHandoff(null);
    setDryRun(null);
    setDiffPreview(null);
    resetMutationState();
  }

  function resetAfterHandoff(result: ExecutionHandoffResponse) {
    setHandoff(result);
    setDryRun(null);
    setDiffPreview(null);
    resetMutationState();
  }

  function resetAfterDryRun(result: CoderDryRunResponse) {
    setDryRun(result);
    setDiffPreview(null);
    resetMutationState();
  }

  function resetAfterDiff(result: CoderDiffPreviewResponse) {
    setDiffPreview(result);
    resetMutationState();
  }

  async function applyDiffPreview() {
    if (!handoff || !dryRun || !diffPreview) {
      return;
    }

    const files = diffPreview.file_previews
      .map((filePreview) => `${filePreview.operation_type}: ${filePreview.relative_path}`)
      .join("\n");
    const confirmed = window.confirm(
      `Applying will modify project files after creating required snapshots.\n\n${files}\n\nContinue?`,
    );

    if (!confirmed) {
      return;
    }

    await runStep(
      "apply",
      () => applyReviewedChanges(handoff, dryRun, diffPreview),
      (result) => {
        setExecution(result);
        setRollback(null);
        setVerifications([]);
        void loadExecutionHistory();
        void selectExecution(result.execution_id);
      },
    );
  }

  async function runSelectedVerification() {
    if (!execution) {
      return;
    }

    await runStep(
      "verify",
      () => runExecutionVerification(execution.execution_id, verificationTypes),
      (result) => {
        setVerifications(result.results);
        void loadExecutionHistory();
        void selectExecution(result.execution_id);
      },
    );
  }

  async function refreshVerificationHistory(executionId: string) {
    await runStep(
      "verify",
      () => listExecutionVerifications(executionId),
      (result) => setVerifications(result.verifications),
    );
  }

  async function rollbackCurrentExecution() {
    if (!execution) {
      return;
    }

    const files = execution.file_results
      .map((fileResult) => `${fileResult.operation_type}: ${fileResult.relative_path}`)
      .join("\n");
    const confirmed = window.confirm(
      `Rollback will restore or remove files changed by execution ${execution.execution_id}.\n\n${files}\n\nContinue?`,
    );

    if (!confirmed) {
      return;
    }

    await runStep(
      "rollback",
      () => rollbackExecution(execution.execution_id),
      (result) => {
        setRollback(result);
        void loadExecutionHistory();
        void selectExecution(result.execution_id);
        if (result.status === "ROLLED_BACK") {
          setExecution((current) =>
            current
              ? {
                  ...current,
                  status: "ROLLED_BACK",
                  rollback_available: false,
                  message: result.message,
                }
              : current,
          );
        }
      },
    );
  }

  function toggleVerificationType(verificationType: string) {
    setVerificationTypes((current) =>
      current.includes(verificationType)
        ? current.filter((item) => item !== verificationType)
        : [...current, verificationType],
    );
  }

  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-zinc-950">
          Execution Review
        </h2>
        <p className="text-sm leading-6 text-zinc-600">
          Planning history, approval state, preflight, handoff, dry-run, and
          diff preview. Preview only - no project files have been modified.
        </p>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        <div className="rounded-md border border-zinc-200 bg-zinc-50 p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium text-zinc-950">Workflow history</p>
            <button
              className="inline-flex h-8 items-center rounded-md border border-zinc-300 bg-white px-3 text-xs font-medium text-zinc-800 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:text-zinc-400"
              disabled={loadingAction !== null}
              type="button"
              onClick={() => void loadHistory()}
            >
              {loadingAction === "history" ? "Loading..." : "Refresh"}
            </button>
          </div>

          <div className="mt-3 max-h-80 space-y-2 overflow-auto pr-1">
            {workflows.length > 0 ? (
              workflows.map((workflow) => (
                <button
                  key={workflow.workflow_id}
                  className={`w-full rounded-md border p-3 text-left transition ${
                    selectedWorkflowId === workflow.workflow_id
                      ? "border-zinc-950 bg-white"
                      : "border-zinc-200 bg-white hover:border-zinc-400"
                  }`}
                  disabled={loadingAction !== null}
                  type="button"
                  onClick={() => void selectWorkflow(workflow.workflow_id)}
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="line-clamp-2 text-sm font-medium text-zinc-950">
                      {workflow.user_task}
                    </p>
                    <StatusBadge value={workflow.approval_status} />
                  </div>
                  <p className="mt-2 break-all text-xs text-zinc-500">
                    {workflow.workflow_id}
                  </p>
                  <p className="mt-1 text-xs text-zinc-500">
                    Updated {formatDate(workflow.updated_at)}
                  </p>
                </button>
              ))
            ) : (
              <p className="text-sm text-zinc-500">No workflows found yet.</p>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-4">
          <ProgressRail items={progress} />

          {error ? (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-3">
              <p className="text-sm leading-6 text-amber-900">{error}</p>
            </div>
          ) : null}

          {selectedWorkflow ? (
            <WorkflowSummary workflow={selectedWorkflow} />
          ) : (
            <div className="rounded-md border border-zinc-200 p-4">
              <p className="text-sm text-zinc-500">
                Select a persisted workflow to inspect the execution review
                pipeline.
              </p>
            </div>
          )}

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
            <StepButton
              disabled={!canRunPreflight}
              label={loadingAction === "preflight" ? "Checking..." : "Run preflight"}
              onClick={() =>
                selectedWorkflow
                  ? void runStep(
                      "preflight",
                      () => runExecutionPreflight(selectedWorkflow.workflow_id),
                      resetAfterPreflight,
                    )
                  : undefined
              }
            />
            <StepButton
              disabled={!canCreateHandoff}
              label={loadingAction === "handoff" ? "Creating..." : "Create handoff"}
              onClick={() =>
                selectedWorkflow
                  ? void runStep(
                      "handoff",
                      () => createExecutionHandoff(selectedWorkflow.workflow_id),
                      resetAfterHandoff,
                    )
                  : undefined
              }
            />
            <StepButton
              disabled={!canRunDryRun}
              label={loadingAction === "dry-run" ? "Running..." : "Run dry-run"}
              onClick={() =>
                handoff
                  ? void runStep("dry-run", () => runCoderDryRun(handoff), resetAfterDryRun)
                  : undefined
              }
            />
            <StepButton
              disabled={!canRunDiff}
              label={loadingAction === "diff" ? "Previewing..." : "Preview diff"}
              onClick={() =>
                dryRun
                  ? void runStep("diff", () => runCoderDiffPreview(dryRun), resetAfterDiff)
                  : undefined
              }
            />
          </div>

          {preflight ? <PreflightCard preflight={preflight} /> : null}
          {handoff ? <HandoffCard handoff={handoff} /> : null}
          {dryRun ? <DryRunCard dryRun={dryRun} /> : null}
          {diffPreview ? <DiffPreviewCard diffPreview={diffPreview} /> : null}
          {diffPreview ? (
            <ApplyReviewCard
              canApply={canApply}
              diffPreview={diffPreview}
              isApplying={loadingAction === "apply"}
              onApply={() => void applyDiffPreview()}
            />
          ) : null}
          {execution ? <ExecutionResultCard execution={execution} /> : null}
          {execution ? (
            <VerificationCard
              canVerify={canVerify}
              isLoading={loadingAction === "verify"}
              onRefresh={() => void refreshVerificationHistory(execution.execution_id)}
              onRun={() => void runSelectedVerification()}
              onToggle={toggleVerificationType}
              selectedTypes={verificationTypes}
              verifications={verifications}
            />
          ) : null}
          {execution ? (
            <RollbackCard
              canRollback={canRollback}
              execution={execution}
              isRollingBack={loadingAction === "rollback"}
              onRollback={() => void rollbackCurrentExecution()}
              rollback={rollback}
            />
          ) : null}
        </div>
      </div>

      <AutonomousTaskSection
        autonomousSessionIdInput={autonomousSessionIdInput}
        autonomousTask={autonomousTask}
        autonomousTaskText={autonomousTaskText}
        autonomousWorkspacePath={autonomousWorkspacePath}
        isContinuing={loadingAction === "autonomous-continue"}
        isLoading={loadingAction === "autonomous-load"}
        isStarting={loadingAction === "autonomous-start"}
        onContinue={() => void continueAutonomousSession()}
        onLoad={() => void loadAutonomousSession()}
        onSessionIdChange={setAutonomousSessionIdInput}
        onStart={() => void startAutonomousSession()}
        onTaskChange={setAutonomousTaskText}
        onWorkspacePathChange={setAutonomousWorkspacePath}
      />

      <GitStatusSection
        commitMessage={gitCommitMessage}
        gitCommit={gitCommit}
        gitStatus={gitStatus}
        isCommitting={loadingAction === "git-commit"}
        isLoading={loadingAction === "git-status"}
        onCommit={() => void commitSelectedExecution()}
        onCommitMessageChange={setGitCommitMessage}
        onRefresh={() => void loadGitStatus()}
      />

      <ControlledTaskSection
        isApplying={loadingAction === "task-apply"}
        isPreparing={loadingAction === "task-prepare"}
        isRollingBack={loadingAction === "task-rollback"}
        isRetrying={loadingAction === "task-retry"}
        isVerifying={loadingAction === "task-verify"}
        onApply={() => void applyPreparedTask()}
        onLoad={() => void loadTaskExecution()}
        onPrepare={() => void prepareSelectedTask()}
        onRollback={() => void rollbackTask()}
        onRetry={() => void retryFailedTask()}
        onTaskIdChange={setTaskExecutionIdInput}
        onVerify={() => void verifyAppliedTask()}
        selectedWorkflow={selectedWorkflow}
        taskExecution={taskExecution}
        taskExecutionIdInput={taskExecutionIdInput}
      />

      <ExecutionHistorySection
        error={executionHistoryError}
        executions={executions}
        isLoading={executionHistoryLoading}
        onRefresh={() => void loadExecutionHistory()}
        onSelect={(executionId) => void selectExecution(executionId)}
        quality={selectedExecutionQuality}
        selectedExecution={selectedExecution}
      />
    </section>
  );
}

function AutonomousTaskSection({
  autonomousSessionIdInput,
  autonomousTask,
  autonomousTaskText,
  autonomousWorkspacePath,
  isContinuing,
  isLoading,
  isStarting,
  onContinue,
  onLoad,
  onSessionIdChange,
  onStart,
  onTaskChange,
  onWorkspacePathChange,
}: {
  autonomousSessionIdInput: string;
  autonomousTask: AutonomousTaskSession | null;
  autonomousTaskText: string;
  autonomousWorkspacePath: string;
  isContinuing: boolean;
  isLoading: boolean;
  isStarting: boolean;
  onContinue: () => void;
  onLoad: () => void;
  onSessionIdChange: (value: string) => void;
  onStart: () => void;
  onTaskChange: (value: string) => void;
  onWorkspacePathChange: (value: string) => void;
}) {
  const isBusy = isContinuing || isLoading || isStarting;
  const canStart = autonomousTaskText.trim().length > 0 && !isBusy;
  const canLoad = autonomousSessionIdInput.trim().length > 0 && !isBusy;
  const canContinue =
    Boolean(autonomousTask) &&
    !["QUALITY_PASSED", "RETRY_LIMIT_REACHED", "ROLLED_BACK", "BLOCKED"].includes(
      autonomousTask?.state ?? "",
    ) &&
    !isBusy;

  return (
    <div className="mt-5 rounded-md border border-zinc-200 bg-white p-4">
      <div className="flex flex-col gap-1">
        <p className="text-sm font-semibold text-zinc-950">Bounded Autonomous Task Mode</p>
        <p className="text-sm leading-6 text-zinc-600">
          Coordinates safe planning, preparation, verification, quality, and retry preparation.
          It stops for plan approval and again for every reviewed diff before mutation.
        </p>
      </div>
      <div className="mt-4 grid gap-2 lg:grid-cols-[1fr_1fr_auto]">
        <input
          className="h-10 min-w-0 rounded-md border border-zinc-300 bg-white px-3 text-sm text-zinc-950 outline-none transition focus:border-zinc-950"
          placeholder="Development task"
          value={autonomousTaskText}
          onChange={(event) => onTaskChange(event.target.value)}
        />
        <input
          className="h-10 min-w-0 rounded-md border border-zinc-300 bg-white px-3 text-sm text-zinc-950 outline-none transition focus:border-zinc-950"
          placeholder="Optional workspace path"
          value={autonomousWorkspacePath}
          onChange={(event) => onWorkspacePathChange(event.target.value)}
        />
        <button
          className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
          disabled={!canStart}
          type="button"
          onClick={onStart}
        >
          {isStarting ? "Starting..." : "Start bounded session"}
        </button>
      </div>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input
          className="h-10 min-w-0 flex-1 rounded-md border border-zinc-300 bg-white px-3 text-sm text-zinc-950 outline-none transition focus:border-zinc-950"
          placeholder="Autonomous session ID"
          value={autonomousSessionIdInput}
          onChange={(event) => onSessionIdChange(event.target.value)}
        />
        <button
          className="inline-flex h-10 w-fit items-center justify-center rounded-md border border-zinc-300 bg-white px-4 text-sm font-medium text-zinc-800 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:text-zinc-400"
          disabled={!canLoad}
          type="button"
          onClick={onLoad}
        >
          {isLoading ? "Loading..." : "Load session"}
        </button>
        <button
          className="inline-flex h-10 w-fit items-center justify-center rounded-md border border-zinc-300 bg-white px-4 text-sm font-medium text-zinc-800 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:text-zinc-400"
          disabled={!canContinue}
          type="button"
          onClick={onContinue}
        >
          {isContinuing ? "Continuing..." : "Continue safe stages"}
        </button>
      </div>
      {autonomousTask ? (
        <div className="mt-4 rounded-md border border-zinc-200 bg-zinc-50 p-4 text-sm leading-6 text-zinc-700">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="break-all font-semibold text-zinc-950">
                {autonomousTask.autonomous_session_id}
              </p>
              <p className="break-all text-xs text-zinc-500">
                Workflow: {autonomousTask.workflow_id ?? "Not created"}
              </p>
            </div>
            <StatusBadge value={autonomousTask.state} />
          </div>
          <p className="mt-3">{autonomousTask.message}</p>
          <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
            <HashRow label="Current stage" value={autonomousTask.current_stage} />
            <HashRow
              label="Waiting for"
              value={autonomousTask.waiting_for ?? "No user action currently required"}
            />
            <HashRow
              label="Attempt"
              value={`${autonomousTask.current_attempt} of ${autonomousTask.max_attempts}`}
            />
            <HashRow
              label="Autonomous mutation"
              value={autonomousTask.mutation_performed_by_autonomous_mode ? "Yes" : "No"}
            />
            <HashRow label="Task execution" value={autonomousTask.task_execution_id ?? "Not prepared"} />
            <HashRow label="Plan fingerprint" value={autonomousTask.plan_fingerprint ?? "Not planned"} />
          </div>
          <ListBlock label="Progress" values={autonomousTask.progress} />
          <ListBlock label="Warnings" values={autonomousTask.warnings} />
          <ListBlock label="Blockers" values={autonomousTask.blockers} />
          {autonomousTask.task_execution ? (
            <div className="mt-3 rounded-md border border-zinc-200 bg-white p-3">
              <p className="text-xs font-semibold uppercase text-zinc-500">Linked task state</p>
              <HashRow label="State" value={autonomousTask.task_execution.state} />
              <HashRow label="Message" value={autonomousTask.task_execution.message} />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function GitStatusSection({
  commitMessage,
  gitCommit,
  gitStatus,
  isCommitting,
  isLoading,
  onCommit,
  onCommitMessageChange,
  onRefresh,
}: {
  commitMessage: string;
  gitCommit: GitCommitResponse | null;
  gitStatus: GitStatusResponse | null;
  isCommitting: boolean;
  isLoading: boolean;
  onCommit: () => void;
  onCommitMessageChange: (value: string) => void;
  onRefresh: () => void;
}) {
  const canCommit =
    Boolean(gitStatus?.execution_id) &&
    Boolean(gitStatus?.is_git_repository) &&
    gitStatus?.unexpected_changed_files.length === 0 &&
    !isCommitting;

  return (
    <div className="mt-5 rounded-md border border-zinc-200 bg-white p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-zinc-950">Read-Only Git Status</p>
          <p className="text-sm leading-6 text-zinc-600">
            Fixed read-only Git checks only. This does not stage, commit, reset, clean, push, or mutate files.
          </p>
        </div>
        <button
          className="inline-flex h-10 w-fit items-center justify-center rounded-md border border-zinc-300 bg-white px-4 text-sm font-medium text-zinc-800 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:text-zinc-400"
          disabled={isLoading}
          type="button"
          onClick={onRefresh}
        >
          {isLoading ? "Reading..." : "Read Git status"}
        </button>
      </div>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input
          className="h-10 min-w-0 flex-1 rounded-md border border-zinc-300 bg-white px-3 text-sm text-zinc-950 outline-none transition focus:border-zinc-950"
          placeholder="Optional conventional commit message"
          value={commitMessage}
          onChange={(event) => onCommitMessageChange(event.target.value)}
        />
        <button
          className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
          disabled={!canCommit}
          type="button"
          onClick={onCommit}
        >
          {isCommitting ? "Committing..." : "Commit verified changes"}
        </button>
      </div>
      {gitStatus ? (
        <div className="mt-4 rounded-md border border-zinc-200 bg-zinc-50 p-4 text-sm leading-6 text-zinc-700">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="break-all font-semibold text-zinc-950">{gitStatus.workspace_path}</p>
            <StatusBadge value={gitStatus.is_git_repository ? "GIT" : "NOT_GIT"} />
          </div>
          <HashRow label="Branch" value={gitStatus.current_branch ?? "Not available"} />
          <HashRow label="Changed files" value={String(gitStatus.changed_file_count)} />
          <ListBlock label="Staged" values={gitStatus.staged_files} />
          <ListBlock label="Unstaged" values={gitStatus.unstaged_files} />
          <ListBlock label="Untracked" values={gitStatus.untracked_files} />
          <ListBlock label="Execution audit files" values={gitStatus.execution_audit_files} />
          <ListBlock label="Unexpected changed files" values={gitStatus.unexpected_changed_files} />
          <ListBlock
            label="Recent commits"
            values={gitStatus.recent_commits.map((commit) => `${commit.commit} ${commit.subject}`)}
          />
          <ListBlock label="Warnings" values={gitStatus.warnings} />
          <ListBlock label="Blockers" values={gitStatus.blockers} />
          {gitStatus.diff_summary ? (
            <pre className="mt-3 max-h-40 overflow-auto rounded-md bg-white p-3 text-xs leading-5 text-zinc-800">
              {gitStatus.diff_summary}
            </pre>
          ) : null}
          {gitStatus.diff_excerpt ? (
            <pre className="mt-3 max-h-80 overflow-auto rounded-md bg-zinc-950 p-3 text-xs leading-5 text-zinc-50">
              {gitStatus.diff_excerpt}
              {gitStatus.diff_truncated ? "\n\n[diff truncated]" : ""}
            </pre>
          ) : null}
        </div>
      ) : null}
      {gitCommit ? (
        <div className="mt-4 rounded-md border border-zinc-200 bg-zinc-50 p-4 text-sm leading-6 text-zinc-700">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="break-all font-semibold text-zinc-950">
              Commit audit: {gitCommit.commit_audit_id}
            </p>
            <StatusBadge value={gitCommit.status} />
          </div>
          <HashRow label="Commit" value={gitCommit.commit_hash ?? "Not committed"} />
          <HashRow label="Message" value={gitCommit.message} />
          <HashRow label="Timestamp" value={formatDate(gitCommit.timestamp)} />
          <ListBlock label="Files committed" values={gitCommit.files_committed} />
          <ListBlock label="Warnings" values={gitCommit.warnings} />
          <ListBlock label="Blockers" values={gitCommit.blockers} />
        </div>
      ) : null}
    </div>
  );
}

function ControlledTaskSection({
  isApplying,
  isPreparing,
  isRollingBack,
  isRetrying,
  isVerifying,
  onApply,
  onLoad,
  onPrepare,
  onRollback,
  onRetry,
  onTaskIdChange,
  onVerify,
  selectedWorkflow,
  taskExecution,
  taskExecutionIdInput,
}: {
  isApplying: boolean;
  isPreparing: boolean;
  isRollingBack: boolean;
  isRetrying: boolean;
  isVerifying: boolean;
  onApply: () => void;
  onLoad: () => void;
  onPrepare: () => void;
  onRollback: () => void;
  onRetry: () => void;
  onTaskIdChange: (value: string) => void;
  onVerify: () => void;
  selectedWorkflow: PlanningWorkflowHistoryRecord | null;
  taskExecution: TaskExecutionSession | null;
  taskExecutionIdInput: string;
}) {
  const canPrepare = selectedWorkflow?.approval_status === "APPROVED" && !isPreparing;
  const canApply = taskExecution?.state === "AWAITING_EXECUTION_APPROVAL" && !isApplying;
  const canVerify =
    ["APPLIED", "QUALITY_FAILED", "QUALITY_INCOMPLETE"].includes(taskExecution?.state ?? "") &&
    !isVerifying;
  const canRollback =
    Boolean(taskExecution?.mutation_execution_id) &&
    taskExecution?.state !== "ROLLED_BACK" &&
    !isRollingBack;
  const canRetry =
    taskExecution?.state === "QUALITY_FAILED" &&
    taskExecution.current_attempt < taskExecution.max_attempts &&
    !isRetrying;
  const remainingAttempts = taskExecution
    ? Math.max(taskExecution.max_attempts - taskExecution.current_attempt, 0)
    : 0;

  return (
    <div className="mt-5 rounded-md border border-zinc-200 bg-zinc-50 p-4">
      <div className="flex flex-col gap-1">
        <p className="text-sm font-semibold text-zinc-950">Controlled Single-Task Execution</p>
        <p className="text-sm leading-6 text-zinc-600">
          Prepare reviewed diffs, explicitly apply, verify required checks, and evaluate the Quality Gate.
          Planning approval alone never applies files.
        </p>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-2 text-xs sm:grid-cols-6">
        {["Prepare", "Review Diff", "Apply", "Verify", "Quality", "Retry"].map((label) => (
          <div key={label} className="rounded-md border border-zinc-200 bg-white px-3 py-2">
            <p className="font-medium text-zinc-900">{label}</p>
          </div>
        ))}
      </div>
      <div className="mt-4 flex flex-col gap-3 lg:flex-row">
        <button
          className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
          disabled={!canPrepare}
          type="button"
          onClick={onPrepare}
        >
          {isPreparing ? "Preparing..." : "Prepare selected workflow"}
        </button>
        <div className="flex flex-1 flex-col gap-2 sm:flex-row">
          <input
            className="h-10 min-w-0 flex-1 rounded-md border border-zinc-300 bg-white px-3 text-sm text-zinc-950 outline-none transition focus:border-zinc-950"
            placeholder="Task execution ID"
            value={taskExecutionIdInput}
            onChange={(event) => onTaskIdChange(event.target.value)}
          />
          <button
            className="inline-flex h-10 w-fit items-center justify-center rounded-md border border-zinc-300 bg-white px-4 text-sm font-medium text-zinc-800 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:text-zinc-400"
            disabled={!taskExecutionIdInput.trim() || isPreparing}
            type="button"
            onClick={onLoad}
          >
            Load task
          </button>
        </div>
      </div>

      {taskExecution ? (
        <div className="mt-4 rounded-md border border-zinc-200 bg-white p-4 text-sm leading-6 text-zinc-700">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="break-all font-semibold text-zinc-950">
                {taskExecution.task_execution_id}
              </p>
              <p className="break-all text-xs text-zinc-500">
                Workflow: {taskExecution.workflow_id}
              </p>
            </div>
            <StatusBadge value={taskExecution.state} />
          </div>
          <p className="mt-3">{taskExecution.message}</p>
          <div className="mt-3 rounded-md border border-zinc-200 bg-zinc-50 p-3 text-xs text-zinc-700">
            <p className="font-semibold text-zinc-950">
              Attempt {taskExecution.current_attempt} of {taskExecution.max_attempts}
            </p>
            <p>
              Remaining improvement retries: {remainingAttempts}. Every retry returns to reviewed diff
              and requires explicit Apply before files can change.
            </p>
          </div>
          {taskExecution.attempts.length > 0 ? (
            <div className="mt-3 rounded-md border border-zinc-200 bg-white p-3">
              <p className="text-xs font-semibold uppercase text-zinc-500">
                Attempt lineage
              </p>
              <div className="mt-2 grid gap-2">
                {taskExecution.attempts.map((attempt) => (
                  <div
                    key={`${attempt.attempt_number}-${attempt.diff_review_id ?? "none"}`}
                    className="rounded-md border border-zinc-200 bg-zinc-50 p-3 text-xs"
                  >
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                      <p className="font-medium text-zinc-950">Attempt {attempt.attempt_number}</p>
                      <StatusBadge value={attempt.state} />
                    </div>
                    <HashRow label="Diff review" value={attempt.diff_review_id ?? "Not prepared"} />
                    <HashRow label="Execution" value={attempt.mutation_execution_id ?? "Not applied"} />
                    <HashRow label="Quality" value={attempt.quality_status ?? "Not evaluated"} />
                    <HashRow
                      label="Parent execution"
                      value={attempt.parent_execution_id ?? "Initial attempt"}
                    />
                    <HashRow
                      label="Failure context"
                      value={attempt.failure_context_hash ?? "Not a retry"}
                    />
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          <ListBlock label="Warnings" values={taskExecution.warnings} />
          <ListBlock label="Blockers" values={taskExecution.blockers} />
          {taskExecution.diff_preview ? (
            <DiffPreviewCard diffPreview={taskExecution.diff_preview} />
          ) : null}
          {taskExecution.apply_result ? (
            <ExecutionResultCard execution={taskExecution.apply_result} />
          ) : null}
          {taskExecution.quality_result ? (
            <QualityGateCard quality={taskExecution.quality_result} />
          ) : null}
          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            <button
              className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-amber-600 px-4 text-sm font-medium text-white transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:bg-zinc-400"
              disabled={!canApply}
              type="button"
              onClick={onApply}
            >
              {isApplying ? "Applying..." : "Apply reviewed task"}
            </button>
            <button
              className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
              disabled={!canVerify}
              type="button"
              onClick={onVerify}
            >
              {isVerifying ? "Verifying..." : "Run required verification"}
            </button>
            <button
              className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-red-700 px-4 text-sm font-medium text-white transition hover:bg-red-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
              disabled={!canRollback}
              type="button"
              onClick={onRollback}
            >
              {isRollingBack ? "Rolling back..." : "Rollback task"}
            </button>
            <button
              className="inline-flex h-10 w-fit items-center justify-center rounded-md border border-zinc-300 bg-white px-4 text-sm font-medium text-zinc-800 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:text-zinc-400"
              disabled={!canRetry}
              type="button"
              onClick={onRetry}
            >
              {isRetrying ? "Preparing retry..." : "Prepare improvement retry"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ExecutionHistorySection({
  error,
  executions,
  isLoading,
  onRefresh,
  onSelect,
  quality,
  selectedExecution,
}: {
  error: string;
  executions: ExecutionHistoryItem[];
  isLoading: boolean;
  onRefresh: () => void;
  onSelect: (executionId: string) => void;
  quality: ExecutionQualityResponse | null;
  selectedExecution: ExecutionHistoryDetail | null;
}) {
  const selectedExecutionId = selectedExecution?.execution_id ?? "";

  return (
    <div className="mt-5 rounded-md border border-zinc-200 bg-zinc-50 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-zinc-950">Execution History</p>
          <p className="mt-1 text-sm leading-6 text-zinc-600">
            Reloadable SQLite audit history for applied, verified, failed, and rolled-back executions,
            with a deterministic Quality Gate for selected records.
          </p>
        </div>
        <button
          className="inline-flex h-8 w-fit items-center rounded-md border border-zinc-300 bg-white px-3 text-xs font-medium text-zinc-800 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:text-zinc-400"
          disabled={isLoading}
          type="button"
          onClick={onRefresh}
        >
          {isLoading ? "Loading..." : "Refresh executions"}
        </button>
      </div>

      {error ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3">
          <p className="text-sm leading-6 text-amber-900">{error}</p>
        </div>
      ) : null}

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        <div className="max-h-96 space-y-2 overflow-auto pr-1">
          {executions.length > 0 ? (
            executions.map((execution) => (
              <button
                key={execution.execution_id}
                className={`w-full rounded-md border bg-white p-3 text-left transition ${
                  selectedExecutionId === execution.execution_id
                    ? "border-zinc-950"
                    : "border-zinc-200 hover:border-zinc-400"
                }`}
                disabled={isLoading}
                type="button"
                onClick={() => onSelect(execution.execution_id)}
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="break-all text-sm font-medium text-zinc-950">
                    {execution.execution_id}
                  </p>
                  <StatusBadge value={execution.status} />
                </div>
                <p className="mt-2 break-all text-xs text-zinc-500">
                  Workflow: {execution.workflow_id}
                </p>
                <p className="mt-1 text-xs text-zinc-500">
                  Created {formatDate(execution.created_at)}
                </p>
                <p className="mt-1 text-xs text-zinc-500">
                  Files: {execution.changed_files.length} | Verifications: {execution.verification_count}
                </p>
              </button>
            ))
          ) : (
            <p className="rounded-md border border-zinc-200 bg-white p-3 text-sm text-zinc-500">
              No execution records found yet.
            </p>
          )}
        </div>

        {selectedExecution ? (
          <ExecutionHistoryDetailCard
            execution={selectedExecution}
            quality={quality}
          />
        ) : (
          <div className="rounded-md border border-zinc-200 bg-white p-4">
            <p className="text-sm text-zinc-500">
              Select an execution to inspect its persisted audit trail after reload.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function ExecutionHistoryDetailCard({
  execution,
  quality,
}: {
  execution: ExecutionHistoryDetail;
  quality: ExecutionQualityResponse | null;
}) {
  return (
    <div className="rounded-md border border-zinc-200 bg-white p-4 text-sm leading-6 text-zinc-700">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="break-all font-semibold text-zinc-950">{execution.execution_id}</p>
          <p className="mt-1 break-all text-xs text-zinc-500">
            Workflow: {execution.workflow_id}
          </p>
          <p className="mt-1 break-all text-xs text-zinc-500">
            Workspace: {execution.workspace_path}
          </p>
        </div>
        <StatusBadge value={execution.status} />
      </div>

      <ExecutionTimeline execution={execution} />
      <QualityGateCard quality={quality} />

      <div className="mt-4 rounded-md bg-zinc-50 p-3">
        <p className="text-xs font-medium uppercase text-zinc-500">Current state</p>
        <p className="mt-1 text-zinc-900">{execution.final_current_state}</p>
      </div>

      <dl className="mt-4 grid grid-cols-1 gap-2 text-xs text-zinc-600 md:grid-cols-2">
        <HashRow label="Created" value={formatDate(execution.created_at)} />
        <HashRow
          label="Completed"
          value={execution.completed_at ? formatDate(execution.completed_at) : "None"}
        />
        <HashRow
          label="Rolled back"
          value={execution.rolled_back_at ? formatDate(execution.rolled_back_at) : "None"}
        />
        <HashRow label="Backup status" value={execution.backup_status} />
        <HashRow
          label="Rollback available"
          value={execution.rollback_available ? "Yes" : "No"}
        />
        <HashRow
          label="Rollback recommendation"
          value={execution.rollback_recommended ? "Recommended" : "Not recommended"}
        />
        <HashRow label="Plan fingerprint" value={execution.plan_fingerprint} />
        <HashRow label="Diff review ID" value={execution.diff_review_id} />
      </dl>

      <ListBlock label="Changed files" values={execution.changed_files} />
      <ListBlock label="Operation types" values={execution.operation_types} />
      <ListBlock label="Warnings" values={execution.warnings} />
      <ListBlock label="Blockers" values={execution.blockers} />

      <div className="mt-4 space-y-3">
        {execution.files.map((file) => (
          <div
            key={`${file.operation_type}:${file.relative_path}`}
            className="rounded-md border border-zinc-200 bg-zinc-50 p-3"
          >
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <p className="break-all text-sm font-medium text-zinc-950">
                {file.relative_path}
              </p>
              <StatusBadge value={file.mutation_status} />
            </div>
            <dl className="mt-3 grid grid-cols-1 gap-2 text-xs text-zinc-600 md:grid-cols-2">
              <HashRow label="Operation" value={file.operation_type} />
              <HashRow label="Backup status" value={file.backup_status} />
              <HashRow label="Original hash" value={file.original_content_hash} />
              <HashRow label="Proposed hash" value={file.proposed_content_hash} />
              <HashRow label="Final hash" value={file.final_content_hash} />
            </dl>
          </div>
        ))}
      </div>

      <div className="mt-4 space-y-4">
        <p className="text-xs font-medium uppercase text-zinc-500">
          Verification history
        </p>
        {execution.verifications.length > 0 ? (
          execution.verifications.map((verification) => (
            <VerificationResult key={verification.verification_id} verification={verification} />
          ))
        ) : (
          <p className="text-zinc-500">No verification runs recorded.</p>
        )}
      </div>
    </div>
  );
}

function ExecutionTimeline({ execution }: { execution: ExecutionHistoryDetail }) {
  const events = [
    { label: "Approved", value: "Workflow approval recorded" },
    { label: "Applied", value: execution.completed_at ? formatDate(execution.completed_at) : null },
    {
      label: "Verified",
      value:
        execution.verifications.length > 0
          ? latestVerificationState(execution.verifications)
          : null,
    },
    {
      label: "Rolled Back",
      value: execution.rolled_back_at ? formatDate(execution.rolled_back_at) : null,
    },
  ].filter((event) => event.value);

  return (
    <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-4">
      {events.map((event) => (
        <div
          key={event.label}
          className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-900"
        >
          <p className="font-medium">{event.label}</p>
          <p className="mt-1 break-words">{event.value}</p>
        </div>
      ))}
    </div>
  );
}

function QualityGateCard({ quality }: { quality: ExecutionQualityResponse | null }) {
  if (!quality) {
    return (
      <div className="mt-4 rounded-md border border-zinc-200 bg-zinc-50 p-3">
        <p className="text-sm text-zinc-500">Quality gate has not loaded yet.</p>
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-md border border-zinc-200 bg-zinc-50 p-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-medium uppercase text-zinc-500">Quality Gate</p>
          <p className="mt-1 text-sm font-semibold text-zinc-950">
            {quality.quality_status.replace("_", " ")}
          </p>
        </div>
        <StatusBadge value={quality.quality_status} />
      </div>
      <p className="mt-2 text-sm text-zinc-700">
        Evaluated {formatDate(quality.quality_timestamp)} from persisted audit state.
      </p>
      <dl className="mt-3 grid grid-cols-1 gap-2 text-xs text-zinc-600 md:grid-cols-2">
        <HashRow label="Execution status" value={quality.execution_status} />
        <HashRow label="Rollback status" value={quality.rollback_status} />
        <HashRow
          label="Rollback recommended"
          value={quality.rollback_recommended ? "Yes" : "No"}
        />
        <HashRow label="Reasons" value={quality.reasons.join(", ") || "None"} />
      </dl>
      <ListBlock label="Required checks" values={quality.required_verification_types} />
      <ListBlock label="Passed checks" values={quality.passed_checks} />
      <ListBlock label="Failed checks" values={quality.failed_checks} />
      <ListBlock label="Missing checks" values={quality.missing_checks} />
      <ListBlock label="Skipped checks" values={quality.skipped_checks} />
      <ListBlock label="Warnings" values={quality.warnings} />
      <ListBlock label="Blockers" values={quality.blockers} />
      {quality.verification_plan ? (
        <div className="mt-4 space-y-2">
          <p className="text-xs font-medium uppercase text-zinc-500">
            Verification selection policy
          </p>
          {quality.verification_plan.checks.map((check) => (
            <div
              key={check.verification_type}
              className="rounded-md border border-zinc-200 bg-white p-2 text-sm text-zinc-700"
            >
              <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                <p className="font-medium text-zinc-900">{check.verification_type}</p>
                <p className="text-xs uppercase text-zinc-500">{check.tier}</p>
              </div>
              <p className="mt-1 text-xs leading-5 text-zinc-600">{check.reason}</p>
              {check.skip_reason ? (
                <p className="mt-1 text-xs leading-5 text-zinc-500">
                  Skipped: {check.skip_reason}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
      <div className="mt-4 space-y-2">
        <p className="text-xs font-medium uppercase text-zinc-500">
          Verification summary
        </p>
        {quality.verification_summary.length > 0 ? (
          quality.verification_summary.map((summary) => (
            <div
              key={summary.verification_type}
              className="flex flex-col gap-1 rounded-md border border-zinc-200 bg-white p-2 sm:flex-row sm:items-center sm:justify-between"
            >
              <p className="text-sm font-medium text-zinc-900">
                {summary.verification_type}
              </p>
              <p className="text-xs text-zinc-600">
                {summary.required ? "Required" : "Optional"} | Runs: {summary.runs} | Latest:{" "}
                {summary.latest_status ?? "None"}
              </p>
            </div>
          ))
        ) : (
          <p className="text-zinc-500">No verification summary available.</p>
        )}
      </div>
    </div>
  );
}

function WorkflowSummary({ workflow }: { workflow: PlanningWorkflowHistoryRecord }) {
  return (
    <div className="rounded-md border border-zinc-200 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-zinc-950">{workflow.user_task}</p>
          <p className="mt-1 break-all text-xs text-zinc-500">
            Workflow ID: {workflow.workflow_id}
          </p>
          <p className="mt-1 break-all text-xs text-zinc-500">
            Fingerprint: {workflow.plan_fingerprint}
          </p>
        </div>
        <StatusBadge value={workflow.approval_status} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
        <SummaryCell label="Planner" value={workflow.planner_output.task_summary} />
        <SummaryCell label="Reviewer" value={workflow.reviewer_output.approval_recommendation} />
        <SummaryCell label="Validator" value={workflow.validator_output.overall_validation_status} />
      </div>

      <div className="mt-4 rounded-md bg-zinc-50 p-3">
        <p className="text-xs font-medium uppercase text-zinc-500">Final workflow status</p>
        <p className="mt-1 text-sm text-zinc-900">
          {workflow.final_reviewed_summary.final_recommendation}
        </p>
        <p className="mt-1 text-xs leading-5 text-zinc-600">
          {workflow.final_reviewed_summary.final_execution_readiness}
        </p>
      </div>
    </div>
  );
}

function PreflightCard({ preflight }: { preflight: ExecutionPreflightResponse }) {
  return (
    <ResultCard title="Preflight" status={preflight.status}>
      <p>{preflight.execution_readiness}</p>
      <p>Workspace: {preflight.workspace.status}</p>
      <ListBlock label="Warnings" values={preflight.warnings} />
      <ListBlock label="Blockers" values={preflight.blockers} />
      <ListBlock label="Detected changes" values={preflight.detected_changes} />
      <ListBlock
        label="File checks"
        values={preflight.file_checks.map(
          (check) => `${check.relative_path} - ${check.kind} - ${check.note}`,
        )}
      />
    </ResultCard>
  );
}

function HandoffCard({ handoff }: { handoff: ExecutionHandoffResponse }) {
  return (
    <ResultCard title="Handoff" status={handoff.execution_allowed ? "EXECUTION ENABLED" : "PREVIEW ONLY"}>
      <p>{handoff.message}</p>
      <ListBlock label="Allowed files" values={handoff.allowed_files} />
      <ListBlock label="Allowed operations" values={handoff.allowed_operation_types} />
      <ListBlock label="Expected tests" values={handoff.expected_tests} />
      <ListBlock label="Rollback requirements" values={handoff.rollback_backup_requirements.requirements} />
    </ResultCard>
  );
}

function DryRunCard({ dryRun }: { dryRun: CoderDryRunResponse }) {
  return (
    <ResultCard title="Dry Run" status={dryRun.execution_performed ? "EXECUTED" : "PREVIEW ONLY"}>
      <p>{dryRun.message}</p>
      <p>{dryRun.proposed_code_change_summary}</p>
      <ListBlock label="Files to modify" values={dryRun.files_would_modify} />
      <ListBlock label="Files to create" values={dryRun.files_would_create} />
      <ListBlock label="Files to delete" values={dryRun.files_would_delete} />
      <ListBlock
        label="Intended operations"
        values={dryRun.intended_operations.map(
          (operation) =>
            `${operation.operation_type} ${operation.relative_path}: ${operation.description}`,
        )}
      />
      <ListBlock label="Tests to run" values={dryRun.tests_to_run} />
      {dryRun.context_selection ? (
        <div className="mt-3 rounded-md border border-zinc-200 bg-white p-3">
          <p className="text-xs font-semibold uppercase text-zinc-500">Selected context</p>
          <HashRow
            label="Budget"
            value={`${dryRun.context_selection.total_bytes} of ${dryRun.context_selection.max_total_bytes} bytes`}
          />
          <ListBlock
            label="Files"
            values={dryRun.context_selection.selected_files.map(
              (file) =>
                `${file.relative_path}: ${file.reason}${file.truncated ? " (truncated)" : ""}`,
            )}
          />
          <ListBlock
            label="Skipped"
            values={dryRun.context_selection.skipped_files.map(
              (file) => `${file.relative_path}: ${file.warning ?? file.reason}`,
            )}
          />
          <ListBlock label="Context warnings" values={dryRun.context_selection.warnings} />
        </div>
      ) : null}
      <ListBlock label="Warnings" values={dryRun.warnings} />
      <ListBlock label="Blockers" values={dryRun.blockers} />
    </ResultCard>
  );
}

function DiffPreviewCard({ diffPreview }: { diffPreview: CoderDiffPreviewResponse }) {
  return (
    <ResultCard title="Diff Preview" status="PREVIEW ONLY">
      <p>{diffPreview.message}</p>
      <p>
        Review ID: {diffPreview.review_id ?? "Not persisted"} | Reviewed:{" "}
        {diffPreview.reviewed_at ? formatDate(diffPreview.reviewed_at) : "Not available"}
      </p>
      <p className="break-all">
        Review fingerprint: {diffPreview.review_fingerprint ?? "Not available"}
      </p>
      <ListBlock label="Warnings" values={diffPreview.warnings} />
      <ListBlock label="Blockers" values={diffPreview.blockers} />
      <div className="mt-4 space-y-4">
        {diffPreview.file_previews.map((filePreview) => (
          <div
            key={`${filePreview.operation_type}:${filePreview.relative_path}`}
            className="rounded-md border border-zinc-200 bg-white p-3"
          >
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <p className="break-all text-sm font-medium text-zinc-950">
                {filePreview.relative_path}
              </p>
              <StatusBadge value={filePreview.operation_type} />
            </div>
            <ListBlock label="File warnings" values={filePreview.warnings} />
            <DiffColumns
              currentContent={filePreview.current_content}
              proposedContent={filePreview.proposed_content}
            />
            <pre className="mt-3 max-h-80 overflow-auto rounded-md bg-zinc-950 p-3 text-xs leading-5 text-zinc-50">
              {filePreview.unified_diff || "No diff generated."}
            </pre>
          </div>
        ))}
      </div>
    </ResultCard>
  );
}

function ApplyReviewCard({
  canApply,
  diffPreview,
  isApplying,
  onApply,
}: {
  canApply: boolean;
  diffPreview: CoderDiffPreviewResponse;
  isApplying: boolean;
  onApply: () => void;
}) {
  return (
    <ResultCard title="Apply Reviewed Changes" status={canApply ? "READY" : "BLOCKED"}>
      <p className="font-medium text-amber-900">Applying will modify project files.</p>
      <p>
        DevLoopAI will use the exact reviewed target content shown above and create
        required snapshots before writing.
      </p>
      <ListBlock
        label="Files that will change"
        values={diffPreview.file_previews.map(
          (filePreview) => `${filePreview.operation_type} ${filePreview.relative_path}`,
        )}
      />
      <button
        className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-amber-600 px-4 text-sm font-medium text-white transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:bg-zinc-400"
        disabled={!canApply}
        type="button"
        onClick={onApply}
      >
        {isApplying ? "Applying..." : "Apply reviewed changes"}
      </button>
    </ResultCard>
  );
}

function ExecutionResultCard({ execution }: { execution: ExecutionApplyResponse }) {
  return (
    <ResultCard title="Execution Result" status={execution.status}>
      <p>{execution.message}</p>
      <p className="break-all">Execution ID: {execution.execution_id}</p>
      <p>Executed: {formatDate(execution.execution_timestamp)}</p>
      <p>Backup status: {execution.backup_status}</p>
      <p>{execution.rollback_available ? "Backup available" : "Rollback unavailable"}</p>
      <ListBlock label="Files attempted" values={execution.files_attempted} />
      <ListBlock label="Files changed" values={execution.files_changed} />
      <ListBlock label="Warnings" values={execution.warnings} />
      <ListBlock label="Blockers" values={execution.blockers} />
      <div className="mt-4 space-y-3">
        {execution.file_results.map((fileResult) => (
          <div
            key={`${fileResult.operation_type}:${fileResult.relative_path}`}
            className="rounded-md border border-zinc-200 bg-white p-3"
          >
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <p className="break-all text-sm font-medium text-zinc-950">
                {fileResult.relative_path}
              </p>
              <StatusBadge value={fileResult.status} />
            </div>
            <dl className="mt-3 grid grid-cols-1 gap-2 text-xs text-zinc-600 md:grid-cols-2">
              <HashRow label="Original hash" value={fileResult.original_content_hash} />
              <HashRow label="Proposed hash" value={fileResult.proposed_content_hash} />
              <HashRow label="Final hash" value={fileResult.final_content_hash} />
              <HashRow label="Backup status" value={fileResult.backup_status} />
              <HashRow label="Backup location" value={fileResult.backup_location} />
              <HashRow label="Operation" value={fileResult.operation_type} />
            </dl>
          </div>
        ))}
      </div>
    </ResultCard>
  );
}

function VerificationCard({
  canVerify,
  isLoading,
  onRefresh,
  onRun,
  onToggle,
  selectedTypes,
  verifications,
}: {
  canVerify: boolean;
  isLoading: boolean;
  onRefresh: () => void;
  onRun: () => void;
  onToggle: (verificationType: string) => void;
  selectedTypes: string[];
  verifications: ExecutionVerificationResult[];
}) {
  const hasRollbackRecommendation = verifications.some(
    (verification) => verification.rollback_recommended,
  );

  return (
    <ResultCard title="Verification" status={latestVerificationState(verifications)}>
      <p>Run only server-allowlisted checks. No arbitrary command input is accepted.</p>
      {hasRollbackRecommendation ? (
        <p className="font-medium text-amber-900">
          Verification failed - rollback recommended.
        </p>
      ) : null}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {SERVER_ALLOWED_VERIFICATIONS.map((verificationType) => (
          <label
            key={verificationType}
            className="flex items-center gap-2 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-800"
          >
            <input
              checked={selectedTypes.includes(verificationType)}
              className="h-4 w-4"
              type="checkbox"
              onChange={() => onToggle(verificationType)}
            />
            <span>{verificationType}</span>
          </label>
        ))}
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <button
          className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
          disabled={!canVerify}
          type="button"
          onClick={onRun}
        >
          {isLoading ? "Running..." : "Run verification"}
        </button>
        <button
          className="inline-flex h-10 w-fit items-center justify-center rounded-md border border-zinc-300 bg-white px-4 text-sm font-medium text-zinc-800 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:text-zinc-400"
          disabled={isLoading}
          type="button"
          onClick={onRefresh}
        >
          Refresh history
        </button>
      </div>
      <div className="mt-4 space-y-4">
        {verifications.length > 0 ? (
          verifications.map((verification) => (
            <VerificationResult key={verification.verification_id} verification={verification} />
          ))
        ) : (
          <p className="text-zinc-500">No verification runs recorded yet.</p>
        )}
      </div>
    </ResultCard>
  );
}

function VerificationResult({
  verification,
}: {
  verification: ExecutionVerificationResult;
}) {
  return (
    <div className="rounded-md border border-zinc-200 bg-white p-3">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <p className="break-all text-sm font-medium text-zinc-950">
          {verification.verification_type}
        </p>
        <StatusBadge value={verification.status} />
      </div>
      <dl className="mt-3 grid grid-cols-1 gap-2 text-xs text-zinc-600 md:grid-cols-2">
        <HashRow label="Exit code" value={verification.exit_code?.toString() ?? "None"} />
        <HashRow label="Duration" value={`${verification.duration_seconds.toFixed(2)}s`} />
        <HashRow label="Command identity" value={verification.command_identity} />
        <HashRow label="Working directory" value={verification.working_directory} />
        <HashRow
          label="Rollback recommendation"
          value={verification.rollback_recommended ? "Recommended" : "Not recommended"}
        />
        <HashRow label="Output truncated" value={verification.output_truncated ? "Yes" : "No"} />
      </dl>
      <ListBlock label="Changed files" values={verification.changed_files} />
      <ListBlock label="Warnings" values={verification.warnings} />
      <ListBlock label="Blockers" values={verification.blockers} />
      <OutputBlock label="Stdout excerpt" value={verification.stdout_excerpt} />
      <OutputBlock label="Stderr excerpt" value={verification.stderr_excerpt} />
    </div>
  );
}

function RollbackCard({
  canRollback,
  execution,
  isRollingBack,
  onRollback,
  rollback,
}: {
  canRollback: boolean;
  execution: ExecutionApplyResponse;
  isRollingBack: boolean;
  onRollback: () => void;
  rollback: ExecutionRollbackResponse | null;
}) {
  return (
    <ResultCard title="Rollback" status={rollback?.status ?? (canRollback ? "AVAILABLE" : "UNAVAILABLE")}>
      {rollback?.status === "ROLLED_BACK" ? (
        <p className="font-medium text-emerald-900">Execution rolled back.</p>
      ) : (
        <p>
          Rollback restores modified files from snapshots and removes files created
          by this execution.
        </p>
      )}
      <ListBlock
        label="Files rollback would restore/remove"
        values={execution.file_results.map(
          (fileResult) => `${fileResult.operation_type} ${fileResult.relative_path}`,
        )}
      />
      {rollback ? (
        <>
          <p>{rollback.message}</p>
          <p>
            Rolled back: {rollback.rolled_back_at ? formatDate(rollback.rolled_back_at) : "Not completed"}
          </p>
          <ListBlock label="Files restored" values={rollback.files_restored} />
          <ListBlock label="Files removed" values={rollback.files_removed} />
          <ListBlock label="Warnings" values={rollback.warnings} />
          <ListBlock label="Blockers" values={rollback.blockers} />
        </>
      ) : null}
      <button
        className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-red-700 px-4 text-sm font-medium text-white transition hover:bg-red-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
        disabled={!canRollback}
        type="button"
        onClick={onRollback}
      >
        {isRollingBack ? "Rolling back..." : "Rollback execution"}
      </button>
    </ResultCard>
  );
}

function DiffColumns({
  currentContent,
  proposedContent,
}: {
  currentContent: string | null;
  proposedContent: string | null;
}) {
  return (
    <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
      <ContentPreview label="Current content" value={currentContent} />
      <ContentPreview label="Proposed content" value={proposedContent} />
    </div>
  );
}

function ContentPreview({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase text-zinc-500">{label}</p>
      <pre className="mt-2 max-h-56 overflow-auto rounded-md border border-zinc-200 bg-zinc-50 p-3 text-xs leading-5 text-zinc-800">
        {value ?? "None"}
      </pre>
    </div>
  );
}

function OutputBlock({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="mt-3 text-xs font-medium uppercase text-zinc-500">{label}</p>
      <pre className="mt-2 max-h-48 overflow-auto rounded-md border border-zinc-200 bg-zinc-50 p-3 text-xs leading-5 text-zinc-800">
        {value || "None"}
      </pre>
    </div>
  );
}

function HashRow({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="font-medium uppercase text-zinc-500">{label}</dt>
      <dd className="mt-1 break-all text-zinc-800">{value ?? "None"}</dd>
    </div>
  );
}

function ResultCard({
  title,
  status,
  children,
}: {
  title: string;
  status: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-zinc-200 bg-zinc-50 p-4 text-sm leading-6 text-zinc-700">
      <div className="flex items-center justify-between gap-3">
        <p className="font-semibold text-zinc-950">{title}</p>
        <StatusBadge value={status} />
      </div>
      <div className="mt-3 space-y-3">{children}</div>
    </div>
  );
}

function ProgressRail({
  items,
}: {
  items: { label: string; active: boolean; state: string }[];
}) {
  return (
    <div className="grid grid-cols-2 gap-2 rounded-md border border-zinc-200 bg-zinc-50 p-3 text-xs sm:grid-cols-3 xl:grid-cols-9">
      {items.map((item) => (
        <div
          key={item.label}
          className={`rounded-md border px-2 py-2 ${
            item.active
              ? "border-emerald-200 bg-emerald-50 text-emerald-900"
              : "border-zinc-200 bg-white text-zinc-500"
          }`}
        >
          <p className="font-medium">{item.label}</p>
          <p className="mt-1 truncate">{item.state}</p>
        </div>
      ))}
    </div>
  );
}

function StepButton({
  disabled,
  label,
  onClick,
}: {
  disabled: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className="inline-flex h-10 items-center justify-center rounded-md bg-zinc-950 px-3 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
      disabled={disabled}
      type="button"
      onClick={onClick}
    >
      {label}
    </button>
  );
}

function SummaryCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-zinc-50 p-3">
      <p className="text-xs font-medium uppercase text-zinc-500">{label}</p>
      <p className="mt-1 text-zinc-900">{value}</p>
    </div>
  );
}

function ListBlock({ label, values }: { label: string; values: string[] }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase text-zinc-500">{label}</p>
      {values.length > 0 ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-zinc-800">
          {values.map((value) => (
            <li className="break-words" key={value}>
              {value}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-zinc-500">None listed</p>
      )}
    </div>
  );
}

function StatusBadge({ value }: { value: string }) {
  return (
    <span className="inline-flex w-fit shrink-0 items-center rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs font-medium text-zinc-700">
      {value}
    </span>
  );
}

function formatDate(value: string) {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

function latestVerificationState(verifications: ExecutionVerificationResult[]) {
  if (verifications.length === 0) {
    return "waiting";
  }

  return verifications[verifications.length - 1]?.status ?? "waiting";
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return `${error.message} HTTP status: ${error.status}.`;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return fallback;
}
