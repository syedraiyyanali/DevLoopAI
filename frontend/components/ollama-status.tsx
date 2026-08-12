"use client";

import { useEffect, useState } from "react";

import {
  ApiError,
  getOllamaStatus,
  type OllamaStatus,
} from "../lib/api-client";

type RequestState =
  | { status: "loading" }
  | { status: "success"; data: OllamaStatus }
  | { status: "error"; message: string };

export default function OllamaStatusPanel() {
  const [requestState, setRequestState] = useState<RequestState>({
    status: "loading",
  });

  useEffect(() => {
    let isMounted = true;

    async function checkOllamaStatus() {
      try {
        const status = await getOllamaStatus();

        if (isMounted) {
          setRequestState({
            status: "success",
            data: status,
          });
        }
      } catch (error: unknown) {
        if (!isMounted) {
          return;
        }

        const message =
          error instanceof ApiError
            ? `${error.message} HTTP status: ${error.status}.`
            : "Unable to check Ollama status.";

        setRequestState({
          status: "error",
          message,
        });
      }
    }

    void checkOllamaStatus();

    return () => {
      isMounted = false;
    };
  }, []);

  if (requestState.status === "loading") {
    return (
      <section
        aria-live="polite"
        className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm"
      >
        <p className="text-sm font-medium text-zinc-600">
          Checking Ollama connection...
        </p>
      </section>
    );
  }

  if (requestState.status === "error") {
    return (
      <section
        aria-live="polite"
        className="rounded-lg border border-amber-200 bg-amber-50 p-5 shadow-sm"
      >
        <div className="flex items-center gap-3">
          <span className="h-2.5 w-2.5 rounded-full bg-amber-500" />
          <h2 className="text-base font-semibold text-amber-950">
            Ollama status unknown
          </h2>
        </div>
        <p className="mt-3 text-sm leading-6 text-amber-800">
          {requestState.message}
        </p>
      </section>
    );
  }

  const status = requestState.data;
  const modelStatus = status.configured_model_available
    ? "Ready"
    : "Model missing";

  return (
    <section
      aria-live="polite"
      className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm"
    >
      <div className="flex items-center gap-3">
        <span
          className={`h-2.5 w-2.5 rounded-full ${
            status.reachable ? "bg-emerald-500" : "bg-rose-500"
          }`}
        />
        <h2 className="text-base font-semibold text-zinc-950">
          Ollama {status.reachable ? "reachable" : "offline"}
        </h2>
      </div>

      <dl className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-zinc-500">Base URL</dt>
          <dd className="mt-1 break-all font-medium text-zinc-950">
            {status.base_url}
          </dd>
        </div>

        <div>
          <dt className="text-zinc-500">Configured model</dt>
          <dd className="mt-1 break-all font-medium text-zinc-950">
            {status.configured_model}
          </dd>
        </div>

        <div>
          <dt className="text-zinc-500">Model status</dt>
          <dd className="mt-1 font-medium text-zinc-950">{modelStatus}</dd>
        </div>

        <div>
          <dt className="text-zinc-500">Installed models</dt>
          <dd className="mt-1 font-medium text-zinc-950">
            {status.models.length}
          </dd>
        </div>
      </dl>

      {status.error ? (
        <p className="mt-4 text-sm leading-6 text-rose-700">{status.error}</p>
      ) : null}
    </section>
  );
}
