"use client";

import { FormEvent, useState } from "react";

import {
  ApiError,
  listWorkspace,
  openWorkspace,
  readWorkspaceFile,
  type WorkspaceEntry,
  type WorkspaceFileContent,
  type WorkspaceListResponse,
  type WorkspaceMetadata,
} from "../lib/api-client";

type WorkspaceStatus =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; workspace: WorkspaceMetadata; listing: WorkspaceListResponse }
  | { status: "error"; message: string };

type FilePreviewStatus =
  | { status: "idle" }
  | { status: "loading"; relativePath: string }
  | { status: "ready"; file: WorkspaceFileContent }
  | { status: "error"; message: string };

export default function WorkspacePanel() {
  const [workspacePath, setWorkspacePath] = useState("");
  const [workspaceStatus, setWorkspaceStatus] = useState<WorkspaceStatus>({
    status: "idle",
  });
  const [filePreviewStatus, setFilePreviewStatus] = useState<FilePreviewStatus>({
    status: "idle",
  });

  const isLoading = workspaceStatus.status === "loading";
  const canOpen = workspacePath.trim().length > 0 && !isLoading;

  async function handleOpenWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedPath = workspacePath.trim();

    if (!trimmedPath) {
      setWorkspaceStatus({
        status: "error",
        message: "Enter a local project folder path.",
      });
      return;
    }

    setWorkspaceStatus({ status: "loading" });
    setFilePreviewStatus({ status: "idle" });

    try {
      const workspace = await openWorkspace(trimmedPath);
      const listing = await listWorkspace(workspace.root_path);

      setWorkspaceStatus({
        status: "ready",
        workspace,
        listing,
      });
    } catch (error: unknown) {
      setWorkspaceStatus({
        status: "error",
        message: getWorkspaceErrorMessage(error),
      });
    }
  }

  async function openDirectory(relativePath: string) {
    if (workspaceStatus.status !== "ready") {
      return;
    }

    setWorkspaceStatus({ status: "loading" });
    setFilePreviewStatus({ status: "idle" });

    try {
      const listing = await listWorkspace(
        workspaceStatus.workspace.root_path,
        relativePath,
      );

      setWorkspaceStatus({
        status: "ready",
        workspace: listing.workspace,
        listing,
      });
    } catch (error: unknown) {
      setWorkspaceStatus({
        status: "error",
        message: getWorkspaceErrorMessage(error),
      });
    }
  }

  async function openFile(entry: WorkspaceEntry) {
    if (workspaceStatus.status !== "ready") {
      return;
    }

    setFilePreviewStatus({
      status: "loading",
      relativePath: entry.relative_path,
    });

    try {
      const file = await readWorkspaceFile(
        workspaceStatus.workspace.root_path,
        entry.relative_path,
      );

      setFilePreviewStatus({
        status: "ready",
        file,
      });
    } catch (error: unknown) {
      setFilePreviewStatus({
        status: "error",
        message: getWorkspaceErrorMessage(error),
      });
    }
  }

  function getWorkspaceErrorMessage(error: unknown): string {
    if (error instanceof ApiError) {
      return `${error.message} HTTP status: ${error.status}.`;
    }

    if (error instanceof Error) {
      return error.message;
    }

    return "Unable to inspect the selected workspace.";
  }

  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-zinc-950">Workspace</h2>
        <p className="text-sm leading-6 text-zinc-600">
          Open a local project folder for read-only inspection.
        </p>
      </div>

      <form className="mt-5 flex flex-col gap-3 sm:flex-row" onSubmit={handleOpenWorkspace}>
        <label className="sr-only" htmlFor="workspace-path">
          Local project folder
        </label>
        <input
          id="workspace-path"
          className="min-h-10 flex-1 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
          disabled={isLoading}
          placeholder="D:\\personal_AI\\DevLoopAI"
          value={workspacePath}
          onChange={(event) => {
            setWorkspacePath(event.target.value);
            if (workspaceStatus.status === "error") {
              setWorkspaceStatus({ status: "idle" });
            }
          }}
        />
        <button
          className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
          disabled={!canOpen}
          type="submit"
        >
          {isLoading ? "Opening..." : "Open"}
        </button>
      </form>

      {workspaceStatus.status === "error" ? (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm leading-6 text-amber-900">
            {workspaceStatus.message}
          </p>
        </div>
      ) : null}

      {workspaceStatus.status === "ready" ? (
        <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="rounded-md border border-zinc-200 bg-zinc-50 p-4">
            <div className="flex flex-col gap-1">
              <p className="text-sm font-medium text-zinc-950">
                {workspaceStatus.workspace.name}
              </p>
              <p className="break-all text-xs text-zinc-500">
                {workspaceStatus.workspace.root_path}
              </p>
            </div>

            <div className="mt-4 flex items-center justify-between gap-3">
              <p className="text-xs font-medium uppercase text-zinc-500">
                {workspaceStatus.listing.relative_path || "root"}
              </p>
              {workspaceStatus.listing.relative_path ? (
                <button
                  className="text-xs font-medium text-zinc-700 transition hover:text-zinc-950"
                  onClick={() => openDirectory(parentPath(workspaceStatus.listing.relative_path))}
                  type="button"
                >
                  Up
                </button>
              ) : null}
            </div>

            <ul className="mt-3 max-h-80 overflow-auto rounded-md border border-zinc-200 bg-white">
              {workspaceStatus.listing.entries.map((entry) => (
                <li className="border-b border-zinc-100 last:border-b-0" key={entry.relative_path}>
                  <button
                    className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm transition hover:bg-zinc-50"
                    onClick={() =>
                      entry.kind === "directory"
                        ? openDirectory(entry.relative_path)
                        : openFile(entry)
                    }
                    type="button"
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-zinc-900">
                        {entry.kind === "directory" ? "[dir] " : ""}
                        {entry.name}
                      </span>
                      <span className="block truncate text-xs text-zinc-500">
                        {entry.relative_path}
                      </span>
                    </span>
                    <span className="shrink-0 text-xs text-zinc-500">
                      {entry.kind === "directory"
                        ? "Folder"
                        : formatBytes(entry.size_bytes ?? 0)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="min-h-80 rounded-md border border-zinc-200 bg-zinc-950 p-4 text-zinc-100">
            {filePreviewStatus.status === "idle" ? (
              <p className="text-sm text-zinc-400">Select a text file to preview.</p>
            ) : null}

            {filePreviewStatus.status === "loading" ? (
              <p className="text-sm text-zinc-400">
                Reading {filePreviewStatus.relativePath}...
              </p>
            ) : null}

            {filePreviewStatus.status === "error" ? (
              <p className="text-sm leading-6 text-amber-200">
                {filePreviewStatus.message}
              </p>
            ) : null}

            {filePreviewStatus.status === "ready" ? (
              <div className="flex h-full flex-col gap-3">
                <div>
                  <p className="break-all text-sm font-medium">
                    {filePreviewStatus.file.relative_path}
                  </p>
                  <p className="mt-1 text-xs text-zinc-400">
                    {formatBytes(filePreviewStatus.file.size_bytes)}
                  </p>
                </div>
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-zinc-900 p-3 text-xs leading-5">
                  {filePreviewStatus.file.content}
                </pre>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function parentPath(relativePath: string): string {
  const parts = relativePath.split("/").filter(Boolean);
  parts.pop();

  return parts.join("/");
}

function formatBytes(sizeBytes: number): string {
  if (sizeBytes < 1024) {
    return `${sizeBytes} B`;
  }

  return `${(sizeBytes / 1024).toFixed(1)} KB`;
}
