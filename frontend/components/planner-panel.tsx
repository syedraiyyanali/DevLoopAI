"use client";

import { FormEvent, useState } from "react";

import {
  ApiError,
  createPlannerPlan,
  type PlannerResponse,
} from "../lib/api-client";

type PlannerStatus =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; plan: PlannerResponse }
  | { status: "error"; message: string };

export default function PlannerPanel() {
  const [task, setTask] = useState("");
  const [workspacePath, setWorkspacePath] = useState("");
  const [constraints, setConstraints] = useState("");
  const [plannerStatus, setPlannerStatus] = useState<PlannerStatus>({
    status: "idle",
  });

  const isLoading = plannerStatus.status === "loading";
  const canPlan = task.trim().length > 0 && !isLoading;

  async function handlePlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedTask = task.trim();

    if (!trimmedTask) {
      setPlannerStatus({
        status: "error",
        message: "Enter a development task before planning.",
      });
      return;
    }

    setPlannerStatus({ status: "loading" });

    try {
      const plan = await createPlannerPlan(
        trimmedTask,
        workspacePath.trim() || undefined,
        constraints
          .split("\n")
          .map((constraint) => constraint.trim())
          .filter(Boolean),
      );

      setPlannerStatus({
        status: "ready",
        plan,
      });
    } catch (error: unknown) {
      setPlannerStatus({
        status: "error",
        message: getPlannerErrorMessage(error),
      });
    }
  }

  function getPlannerErrorMessage(error: unknown): string {
    if (error instanceof ApiError) {
      return `${error.message} HTTP status: ${error.status}.`;
    }

    if (error instanceof Error) {
      return error.message;
    }

    return "Unable to create a planner response.";
  }

  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-zinc-950">
          Planner Agent
        </h2>
        <p className="text-sm leading-6 text-zinc-600">
          Create a read-only implementation plan from a task and optional project
          context.
        </p>
      </div>

      <form className="mt-5 flex flex-col gap-3" onSubmit={handlePlan}>
        <label className="sr-only" htmlFor="planner-task">
          Development task
        </label>
        <textarea
          id="planner-task"
          className="min-h-24 resize-y rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm leading-6 text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
          disabled={isLoading}
          placeholder="Describe the development task to plan..."
          value={task}
          onChange={(event) => {
            setTask(event.target.value);
            if (plannerStatus.status === "error") {
              setPlannerStatus({ status: "idle" });
            }
          }}
        />

        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <input
            aria-label="Workspace path"
            className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
            disabled={isLoading}
            placeholder="Optional workspace path"
            value={workspacePath}
            onChange={(event) => setWorkspacePath(event.target.value)}
          />
          <textarea
            aria-label="Constraints"
            className="min-h-10 resize-y rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm leading-6 text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
            disabled={isLoading}
            placeholder="Optional constraints, one per line"
            value={constraints}
            onChange={(event) => setConstraints(event.target.value)}
          />
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-zinc-500">
            Planning is read-only; it does not edit files or run commands.
          </p>
          <button
            className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
            disabled={!canPlan}
            type="submit"
          >
            {isLoading ? "Planning..." : "Create plan"}
          </button>
        </div>
      </form>

      {plannerStatus.status === "error" ? (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm leading-6 text-amber-900">
            {plannerStatus.message}
          </p>
        </div>
      ) : null}

      {plannerStatus.status === "ready" ? (
        <div className="mt-5 rounded-md border border-zinc-200 bg-zinc-50 p-4">
          <div className="flex flex-col gap-1">
            <p className="text-sm font-medium text-zinc-950">
              {plannerStatus.plan.task_summary}
            </p>
            <p className="text-xs text-zinc-500">
              Model: {plannerStatus.plan.model}
            </p>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 text-sm lg:grid-cols-2">
            <PlanList
              label="Implementation steps"
              values={plannerStatus.plan.implementation_steps}
            />
            <PlanList
              label="Files likely to change"
              values={plannerStatus.plan.files_likely_to_change}
            />
            <PlanList
              label="Tests"
              values={plannerStatus.plan.tests_verification_required}
            />
            <PlanList label="Risks" values={plannerStatus.plan.risks} />
            <PlanList
              label="Assumptions"
              values={plannerStatus.plan.assumptions}
            />
            <PlanList
              label="Input needed"
              values={plannerStatus.plan.dependencies_or_user_input_needed}
            />
          </div>
        </div>
      ) : null}
    </section>
  );
}

function PlanList({ label, values }: { label: string; values: string[] }) {
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
