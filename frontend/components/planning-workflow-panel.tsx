"use client";

import { FormEvent, useState } from "react";

import {
  ApiError,
  approvePlanningWorkflow,
  rejectPlanningWorkflow,
  runPlanningWorkflow,
  type PlanningApprovalActionResponse,
  type PlanningWorkflowResponse,
} from "../lib/api-client";

type WorkflowStatus =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; workflow: PlanningWorkflowResponse }
  | { status: "error"; message: string };

export default function PlanningWorkflowPanel() {
  const [task, setTask] = useState("");
  const [workspacePath, setWorkspacePath] = useState("");
  const [constraints, setConstraints] = useState("");
  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatus>({
    status: "idle",
  });
  const [approvalResult, setApprovalResult] =
    useState<PlanningApprovalActionResponse | null>(null);
  const [approvalError, setApprovalError] = useState("");
  const [isApprovalLoading, setIsApprovalLoading] = useState(false);

  const isLoading = workflowStatus.status === "loading";
  const canRun = task.trim().length > 0 && !isLoading && !isApprovalLoading;

  async function handleRunWorkflow(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedTask = task.trim();

    if (!trimmedTask) {
      setWorkflowStatus({
        status: "error",
        message: "Enter a development task before running the workflow.",
      });
      return;
    }

    setWorkflowStatus({ status: "loading" });
    setApprovalResult(null);
    setApprovalError("");

    try {
      const workflow = await runPlanningWorkflow(
        trimmedTask,
        workspacePath.trim() || undefined,
        constraints
          .split("\n")
          .map((constraint) => constraint.trim())
          .filter(Boolean),
      );

      setWorkflowStatus({
        status: "ready",
        workflow,
      });
    } catch (error: unknown) {
      setWorkflowStatus({
        status: "error",
        message: getWorkflowErrorMessage(error),
      });
    }
  }

  function getWorkflowErrorMessage(error: unknown): string {
    if (error instanceof ApiError) {
      return `${error.message} HTTP status: ${error.status}.`;
    }

    if (error instanceof Error) {
      return error.message;
    }

    return "Unable to run the planning workflow.";
  }

  async function handleApprovalAction(action: "approve" | "reject") {
    if (workflowStatus.status !== "ready") {
      return;
    }

    setIsApprovalLoading(true);
    setApprovalError("");

    try {
      const result =
        action === "approve"
          ? await approvePlanningWorkflow(workflowStatus.workflow.approval)
          : await rejectPlanningWorkflow(workflowStatus.workflow.approval);

      setApprovalResult(result);
    } catch (error: unknown) {
      setApprovalError(getWorkflowErrorMessage(error));
    } finally {
      setIsApprovalLoading(false);
    }
  }

  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-zinc-950">
          Planning Workflow
        </h2>
        <p className="text-sm leading-6 text-zinc-600">
          Run Planner Agent, Reviewer Agent, Validator Agent, and a final
          read-only execution decision.
        </p>
      </div>

      <form className="mt-5 flex flex-col gap-3" onSubmit={handleRunWorkflow}>
        <label className="sr-only" htmlFor="workflow-task">
          Development task
        </label>
        <textarea
          id="workflow-task"
          className="min-h-24 resize-y rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm leading-6 text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
          disabled={isLoading}
          placeholder="Describe the development task to plan, review, and validate..."
          value={task}
          onChange={(event) => {
            setTask(event.target.value);
            if (workflowStatus.status === "error") {
              setWorkflowStatus({ status: "idle" });
            }
          }}
        />

        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <input
            aria-label="Workflow workspace path"
            className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
            disabled={isLoading}
            placeholder="Optional workspace path"
            value={workspacePath}
            onChange={(event) => setWorkspacePath(event.target.value)}
          />
          <textarea
            aria-label="Workflow constraints"
            className="min-h-10 resize-y rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm leading-6 text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
            disabled={isLoading}
            placeholder="Optional constraints, one per line"
            value={constraints}
            onChange={(event) => setConstraints(event.target.value)}
          />
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-zinc-500">
            Workflow is read-only; it plans, reviews, and validates without
            executing.
          </p>
          <button
            className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
            disabled={!canRun}
            type="submit"
          >
            {isLoading ? "Running..." : "Run workflow"}
          </button>
        </div>
      </form>

      {workflowStatus.status === "error" ? (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm leading-6 text-amber-900">
            {workflowStatus.message}
          </p>
        </div>
      ) : null}

      {workflowStatus.status === "ready" ? (
        <div className="mt-5 rounded-md border border-zinc-200 bg-zinc-50 p-4">
          <div className="flex flex-col gap-1">
            <p className="text-sm font-medium text-zinc-950">
              {workflowStatus.workflow.final_reviewed_summary.summary}
            </p>
            <p className="text-xs text-zinc-500">
              {workflowStatus.workflow.final_reviewed_summary.final_recommendation}
              {workflowStatus.workflow.final_reviewed_summary.user_approval_required
                ? " - User approval required"
                : " - Approval blocked until blockers are resolved"}
            </p>
            <p className="text-xs leading-5 text-zinc-600">
              {
                workflowStatus.workflow.final_reviewed_summary
                  .final_execution_readiness
              }
            </p>
            <p className="text-xs leading-5 text-zinc-600">
              Approval status:{" "}
              {approvalResult?.status ?? workflowStatus.workflow.approval.status}
              {" - "}
              {approvalResult?.message ?? workflowStatus.workflow.approval.reason}
            </p>
            <p className="text-xs leading-5 text-zinc-500">
              Approval only records your decision for this exact reviewed plan;
              it does not execute code or modify files.
            </p>
          </div>

          <div className="mt-4 flex flex-col gap-3 border-t border-zinc-200 pt-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-zinc-500">
              Plan fingerprint:{" "}
              {workflowStatus.workflow.approval.plan_fingerprint.slice(0, 12)}
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                className="inline-flex h-9 w-fit items-center justify-center rounded-md bg-emerald-700 px-3 text-sm font-medium text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
                disabled={
                  isApprovalLoading ||
                  !workflowStatus.workflow.approval.approval_allowed ||
                  approvalResult?.status === "APPROVED" ||
                  approvalResult?.status === "REJECTED"
                }
                type="button"
                onClick={() => void handleApprovalAction("approve")}
              >
                {isApprovalLoading ? "Saving..." : "Approve plan"}
              </button>
              <button
                className="inline-flex h-9 w-fit items-center justify-center rounded-md border border-zinc-300 bg-white px-3 text-sm font-medium text-zinc-800 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:text-zinc-400"
                disabled={
                  isApprovalLoading ||
                  approvalResult?.status === "APPROVED" ||
                  approvalResult?.status === "REJECTED"
                }
                type="button"
                onClick={() => void handleApprovalAction("reject")}
              >
                Reject plan
              </button>
            </div>
          </div>

          {approvalError ? (
            <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3">
              <p className="text-sm leading-6 text-amber-900">{approvalError}</p>
            </div>
          ) : null}

          <div className="mt-4 grid grid-cols-1 gap-4 text-sm lg:grid-cols-2">
            <WorkflowList
              label="Blockers"
              values={workflowStatus.workflow.final_reviewed_summary.blockers}
            />
            <WorkflowList
              label="Warnings"
              values={workflowStatus.workflow.final_reviewed_summary.warnings}
            />
            <WorkflowList
              label="Required changes"
              values={
                workflowStatus.workflow.final_reviewed_summary
                  .required_changes_before_execution
              }
            />
            <WorkflowList
              label="Risks"
              values={workflowStatus.workflow.final_reviewed_summary.risks}
            />
            <WorkflowList
              label="Tests expected"
              values={
                workflowStatus.workflow.final_reviewed_summary.tests_expected
              }
            />
            <WorkflowList
              label="Planner steps"
              values={workflowStatus.workflow.planner_output.implementation_steps}
            />
            <WorkflowList
              label="Validator readiness"
              values={[
                workflowStatus.workflow.validator_output.final_execution_readiness,
              ]}
            />
          </div>
        </div>
      ) : null}
    </section>
  );
}

function WorkflowList({ label, values }: { label: string; values: string[] }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase text-zinc-500">{label}</p>
      {values.length > 0 ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-zinc-900">
          {values.map((value) => (
            <li key={value}>{value}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-zinc-500">None listed</p>
      )}
    </div>
  );
}
