"use client";

import { FormEvent, useState } from "react";

import {
  ApiError,
  validateReviewedPlan,
  type PlannerResponse,
  type ReviewerResponse,
  type ValidatorResponse,
} from "../lib/api-client";

type ValidatorStatus =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; validation: ValidatorResponse }
  | { status: "error"; message: string };

export default function ValidatorPanel() {
  const [task, setTask] = useState("");
  const [plannerJson, setPlannerJson] = useState("");
  const [reviewerJson, setReviewerJson] = useState("");
  const [constraints, setConstraints] = useState("");
  const [validatorStatus, setValidatorStatus] = useState<ValidatorStatus>({
    status: "idle",
  });

  const isLoading = validatorStatus.status === "loading";
  const canValidate =
    task.trim().length > 0 &&
    plannerJson.trim().length > 0 &&
    reviewerJson.trim().length > 0 &&
    !isLoading;

  async function handleValidate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedTask = task.trim();

    if (!trimmedTask || !plannerJson.trim() || !reviewerJson.trim()) {
      setValidatorStatus({
        status: "error",
        message: "Enter the task, planner JSON, and reviewer JSON before validating.",
      });
      return;
    }

    let plannerOutput: PlannerResponse;
    let reviewerOutput: ReviewerResponse;

    try {
      plannerOutput = JSON.parse(plannerJson) as PlannerResponse;
      reviewerOutput = JSON.parse(reviewerJson) as ReviewerResponse;
    } catch {
      setValidatorStatus({
        status: "error",
        message: "Planner and reviewer outputs must be valid JSON.",
      });
      return;
    }

    setValidatorStatus({ status: "loading" });

    try {
      const validation = await validateReviewedPlan(
        trimmedTask,
        plannerOutput,
        reviewerOutput,
        constraints
          .split("\n")
          .map((constraint) => constraint.trim())
          .filter(Boolean),
      );

      setValidatorStatus({
        status: "ready",
        validation,
      });
    } catch (error: unknown) {
      setValidatorStatus({
        status: "error",
        message: getValidatorErrorMessage(error),
      });
    }
  }

  function getValidatorErrorMessage(error: unknown): string {
    if (error instanceof ApiError) {
      return `${error.message} HTTP status: ${error.status}.`;
    }

    if (error instanceof Error) {
      return error.message;
    }

    return "Unable to create a validator response.";
  }

  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-zinc-950">
          Validator Agent
        </h2>
        <p className="text-sm leading-6 text-zinc-600">
          Validate a reviewed plan before any future execution.
        </p>
      </div>

      <form className="mt-5 flex flex-col gap-3" onSubmit={handleValidate}>
        <label className="sr-only" htmlFor="validator-task">
          Original task
        </label>
        <textarea
          id="validator-task"
          className="min-h-20 resize-y rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm leading-6 text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
          disabled={isLoading}
          placeholder="Original user task..."
          value={task}
          onChange={(event) => {
            setTask(event.target.value);
            if (validatorStatus.status === "error") {
              setValidatorStatus({ status: "idle" });
            }
          }}
        />

        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <textarea
            aria-label="Validator planner JSON"
            className="min-h-32 resize-y rounded-md border border-zinc-300 bg-white px-3 py-2 font-mono text-xs leading-5 text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
            disabled={isLoading}
            placeholder="Paste Planner Agent JSON output..."
            value={plannerJson}
            onChange={(event) => setPlannerJson(event.target.value)}
          />
          <textarea
            aria-label="Validator reviewer JSON"
            className="min-h-32 resize-y rounded-md border border-zinc-300 bg-white px-3 py-2 font-mono text-xs leading-5 text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
            disabled={isLoading}
            placeholder="Paste Reviewer Agent JSON output..."
            value={reviewerJson}
            onChange={(event) => setReviewerJson(event.target.value)}
          />
        </div>

        <textarea
          aria-label="Validator constraints"
          className="min-h-10 resize-y rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm leading-6 text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
          disabled={isLoading}
          placeholder="Optional validation constraints, one per line"
          value={constraints}
          onChange={(event) => setConstraints(event.target.value)}
        />

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-zinc-500">
            Validation is read-only; it does not execute commands or modify files.
          </p>
          <button
            className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
            disabled={!canValidate}
            type="submit"
          >
            {isLoading ? "Validating..." : "Validate plan"}
          </button>
        </div>
      </form>

      {validatorStatus.status === "error" ? (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm leading-6 text-amber-900">
            {validatorStatus.message}
          </p>
        </div>
      ) : null}

      {validatorStatus.status === "ready" ? (
        <div className="mt-5 rounded-md border border-zinc-200 bg-zinc-50 p-4">
          <div className="flex flex-col gap-1">
            <p className="text-sm font-medium text-zinc-950">
              {validatorStatus.validation.overall_validation_status}
            </p>
            <p className="text-xs text-zinc-500">
              {validatorStatus.validation.final_execution_readiness} · Model:{" "}
              {validatorStatus.validation.model}
            </p>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 text-sm lg:grid-cols-2">
            <ValidationList
              label="Blockers"
              values={validatorStatus.validation.blockers}
            />
            <ValidationList
              label="File/path validity"
              values={validatorStatus.validation.file_path_validity}
            />
            <ValidationList
              label="Dependency concerns"
              values={validatorStatus.validation.dependency_concerns}
            />
            <ValidationList
              label="Security concerns"
              values={validatorStatus.validation.security_concerns}
            />
            <ValidationList
              label="Destructive warnings"
              values={validatorStatus.validation.destructive_operation_warnings}
            />
            <ValidationList
              label="Tests"
              values={validatorStatus.validation.test_verification_readiness}
            />
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ValidationList({ label, values }: { label: string; values: string[] }) {
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
