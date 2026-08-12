"use client";

import { useEffect, useState } from "react";

import {
  ApiError,
  getBackendHealth,
  type BackendHealth,
} from "../lib/api-client";

type RequestState =
  | { status: "loading" }
  | { status: "success"; data: BackendHealth }
  | { status: "error"; message: string };

export default function BackendStatus() {
  const [requestState, setRequestState] = useState<RequestState>({
    status: "loading",
  });

  useEffect(() => {
    let isMounted = true;

    async function checkBackendHealth() {
      try {
        const health = await getBackendHealth();

        if (isMounted) {
          setRequestState({
            status: "success",
            data: health,
          });
        }
      } catch (error: unknown) {
        if (!isMounted) {
          return;
        }

        const message =
          error instanceof ApiError
            ? `${error.message} HTTP status: ${error.status}.`
            : "Unable to connect to the DevLoopAI backend.";

        setRequestState({
          status: "error",
          message,
        });
      }
    }

    void checkBackendHealth();

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
          Checking backend connection...
        </p>
      </section>
    );
  }

  if (requestState.status === "error") {
    return (
      <section
        aria-live="polite"
        className="rounded-lg border border-rose-200 bg-rose-50 p-5 shadow-sm"
      >
        <div className="flex items-center gap-3">
          <span className="h-2.5 w-2.5 rounded-full bg-rose-500" />
          <h2 className="text-base font-semibold text-rose-950">
            Backend offline
          </h2>
        </div>
        <p className="mt-3 text-sm leading-6 text-rose-800">
          {requestState.message}
        </p>
      </section>
    );
  }

  return (
    <section
      aria-live="polite"
      className="rounded-lg border border-emerald-200 bg-white p-5 shadow-sm"
    >
      <div className="flex items-center gap-3">
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
        <h2 className="text-base font-semibold text-zinc-950">
          Backend connected
        </h2>
      </div>

      <dl className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-zinc-500">Status</dt>
          <dd className="mt-1 font-medium text-zinc-950">
            {requestState.data.status}
          </dd>
        </div>

        <div>
          <dt className="text-zinc-500">Service</dt>
          <dd className="mt-1 font-medium text-zinc-950">
            {requestState.data.service}
          </dd>
        </div>

        <div>
          <dt className="text-zinc-500">Version</dt>
          <dd className="mt-1 font-medium text-zinc-950">
            {requestState.data.version}
          </dd>
        </div>

        <div>
          <dt className="text-zinc-500">Environment</dt>
          <dd className="mt-1 font-medium text-zinc-950">
            {requestState.data.environment}
          </dd>
        </div>
      </dl>
    </section>
  );
}
