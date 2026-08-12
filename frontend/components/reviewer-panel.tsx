"use client";

import { FormEvent, useState } from "react";

import {
  ApiError,
  reviewPlannerOutput,
  type PlannerResponse,
  type ReviewerResponse,
} from "../lib/api-client";

type ReviewerStatus =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; review: ReviewerResponse }
  | { status: "error"; message: string };

export default function ReviewerPanel() {
  const [task, setTask] = useState("");
  const [plannerJson, setPlannerJson] = useState("");
  const [constraints, setConstraints] = useState("");
  const [reviewerStatus, setReviewerStatus] = useState<ReviewerStatus>({
    status: "idle",
  });

  const isLoading = reviewerStatus.status === "loading";
  const canReview = task.trim().length > 0 && plannerJson.trim().length > 0 && !isLoading;

  async function handleReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedTask = task.trim();

    if (!trimmedTask || !plannerJson.trim()) {
      setReviewerStatus({
        status: "error",
        message: "Enter the original task and planner JSON before reviewing.",
      });
      return;
    }

    let plannerOutput: PlannerResponse;

    try {
      plannerOutput = JSON.parse(plannerJson) as PlannerResponse;
    } catch {
      setReviewerStatus({
        status: "error",
        message: "Planner output must be valid JSON.",
      });
      return;
    }

    setReviewerStatus({ status: "loading" });

    try {
      const review = await reviewPlannerOutput(
        trimmedTask,
        plannerOutput,
        constraints
          .split("\n")
          .map((constraint) => constraint.trim())
          .filter(Boolean),
      );

      setReviewerStatus({
        status: "ready",
        review,
      });
    } catch (error: unknown) {
      setReviewerStatus({
        status: "error",
        message: getReviewerErrorMessage(error),
      });
    }
  }

  function getReviewerErrorMessage(error: unknown): string {
    if (error instanceof ApiError) {
      return `${error.message} HTTP status: ${error.status}.`;
    }

    if (error instanceof Error) {
      return error.message;
    }

    return "Unable to create a reviewer response.";
  }

  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-zinc-950">
          Reviewer Agent
        </h2>
        <p className="text-sm leading-6 text-zinc-600">
          Critique a Planner Agent output before any future execution.
        </p>
      </div>

      <form className="mt-5 flex flex-col gap-3" onSubmit={handleReview}>
        <label className="sr-only" htmlFor="reviewer-task">
          Original task
        </label>
        <textarea
          id="reviewer-task"
          className="min-h-20 resize-y rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm leading-6 text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
          disabled={isLoading}
          placeholder="Original user task..."
          value={task}
          onChange={(event) => {
            setTask(event.target.value);
            if (reviewerStatus.status === "error") {
              setReviewerStatus({ status: "idle" });
            }
          }}
        />

        <textarea
          aria-label="Planner JSON"
          className="min-h-32 resize-y rounded-md border border-zinc-300 bg-white px-3 py-2 font-mono text-xs leading-5 text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
          disabled={isLoading}
          placeholder="Paste Planner Agent JSON output..."
          value={plannerJson}
          onChange={(event) => setPlannerJson(event.target.value)}
        />

        <textarea
          aria-label="Reviewer constraints"
          className="min-h-10 resize-y rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm leading-6 text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
          disabled={isLoading}
          placeholder="Optional review constraints, one per line"
          value={constraints}
          onChange={(event) => setConstraints(event.target.value)}
        />

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-zinc-500">
            Review is read-only; it does not execute or modify the plan.
          </p>
          <button
            className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
            disabled={!canReview}
            type="submit"
          >
            {isLoading ? "Reviewing..." : "Review plan"}
          </button>
        </div>
      </form>

      {reviewerStatus.status === "error" ? (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm leading-6 text-amber-900">
            {reviewerStatus.message}
          </p>
        </div>
      ) : null}

      {reviewerStatus.status === "ready" ? (
        <div className="mt-5 rounded-md border border-zinc-200 bg-zinc-50 p-4">
          <div className="flex flex-col gap-1">
            <p className="text-sm font-medium text-zinc-950">
              {reviewerStatus.review.overall_assessment}
            </p>
            <p className="text-xs text-zinc-500">
              {reviewerStatus.review.approval_recommendation} · Model:{" "}
              {reviewerStatus.review.model}
            </p>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 text-sm lg:grid-cols-2">
            <ReviewList label="Missing steps" values={reviewerStatus.review.missing_steps} />
            <ReviewList
              label="Incorrect assumptions"
              values={reviewerStatus.review.incorrect_assumptions}
            />
            <ReviewList
              label="Architecture concerns"
              values={reviewerStatus.review.architecture_concerns}
            />
            <ReviewList
              label="Security concerns"
              values={reviewerStatus.review.security_concerns}
            />
            <ReviewList
              label="Performance concerns"
              values={reviewerStatus.review.performance_concerns}
            />
            <ReviewList label="Testing gaps" values={reviewerStatus.review.testing_gaps} />
            <ReviewList
              label="Unnecessary changes"
              values={reviewerStatus.review.unnecessary_changes}
            />
            <ReviewList
              label="Recommended improvements"
              values={reviewerStatus.review.recommended_improvements}
            />
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ReviewList({ label, values }: { label: string; values: string[] }) {
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
