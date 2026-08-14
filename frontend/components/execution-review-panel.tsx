"use client";

import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createExecutionHandoff,
  getPlanningWorkflowHistory,
  listPlanningWorkflowHistory,
  runCoderDiffPreview,
  runCoderDryRun,
  runExecutionPreflight,
  type CoderDiffPreviewResponse,
  type CoderDryRunResponse,
  type ExecutionHandoffResponse,
  type ExecutionPreflightResponse,
  type PlanningWorkflowHistoryItem,
  type PlanningWorkflowHistoryRecord,
} from "../lib/api-client";

type LoadingAction = "history" | "workflow" | "preflight" | "handoff" | "dry-run" | "diff" | null;

export default function ExecutionReviewPanel() {
  const [workflows, setWorkflows] = useState<PlanningWorkflowHistoryItem[]>([]);
  const [selectedWorkflow, setSelectedWorkflow] =
    useState<PlanningWorkflowHistoryRecord | null>(null);
  const [preflight, setPreflight] = useState<ExecutionPreflightResponse | null>(null);
  const [handoff, setHandoff] = useState<ExecutionHandoffResponse | null>(null);
  const [dryRun, setDryRun] = useState<CoderDryRunResponse | null>(null);
  const [diffPreview, setDiffPreview] = useState<CoderDiffPreviewResponse | null>(null);
  const [loadingAction, setLoadingAction] = useState<LoadingAction>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void loadHistory();
  }, []);

  const selectedWorkflowId = selectedWorkflow?.workflow_id ?? "";
  const canRunPreflight = Boolean(selectedWorkflow) && loadingAction === null;
  const canCreateHandoff =
    preflight?.status === "READY_FOR_EXECUTION" && loadingAction === null;
  const canRunDryRun = Boolean(handoff) && loadingAction === null;
  const canRunDiff = Boolean(dryRun) && loadingAction === null;
  const progress = useMemo(
    () => [
      { label: "Planning", active: Boolean(selectedWorkflow), state: selectedWorkflow ? "ready" : "waiting" },
      { label: "Approval", active: selectedWorkflow?.approval_status === "APPROVED", state: selectedWorkflow?.approval_status ?? "waiting" },
      { label: "Preflight", active: preflight?.status === "READY_FOR_EXECUTION", state: preflight?.status ?? "waiting" },
      { label: "Handoff", active: Boolean(handoff), state: handoff ? "ready" : "waiting" },
      { label: "Dry Run", active: Boolean(dryRun), state: dryRun ? "ready" : "waiting" },
      { label: "Diff", active: Boolean(diffPreview), state: diffPreview ? "ready" : "waiting" },
    ],
    [diffPreview, dryRun, handoff, preflight, selectedWorkflow],
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
  }

  function resetAfterPreflight(result: ExecutionPreflightResponse) {
    setPreflight(result);
    setHandoff(null);
    setDryRun(null);
    setDiffPreview(null);
  }

  function resetAfterHandoff(result: ExecutionHandoffResponse) {
    setHandoff(result);
    setDryRun(null);
    setDiffPreview(null);
  }

  function resetAfterDryRun(result: CoderDryRunResponse) {
    setDryRun(result);
    setDiffPreview(null);
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
                  ? void runStep("diff", () => runCoderDiffPreview(dryRun), setDiffPreview)
                  : undefined
              }
            />
          </div>

          {preflight ? <PreflightCard preflight={preflight} /> : null}
          {handoff ? <HandoffCard handoff={handoff} /> : null}
          {dryRun ? <DryRunCard dryRun={dryRun} /> : null}
          {diffPreview ? <DiffPreviewCard diffPreview={diffPreview} /> : null}
        </div>
      </div>
    </section>
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
      <ListBlock label="Warnings" values={dryRun.warnings} />
      <ListBlock label="Blockers" values={dryRun.blockers} />
    </ResultCard>
  );
}

function DiffPreviewCard({ diffPreview }: { diffPreview: CoderDiffPreviewResponse }) {
  return (
    <ResultCard title="Diff Preview" status="PREVIEW ONLY">
      <p>{diffPreview.message}</p>
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
    <div className="grid grid-cols-2 gap-2 rounded-md border border-zinc-200 bg-zinc-50 p-3 text-xs sm:grid-cols-6">
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

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return `${error.message} HTTP status: ${error.status}.`;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return fallback;
}
