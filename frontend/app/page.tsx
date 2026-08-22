import BackendStatus from "../components/backend-status";
import ChatPanel from "../components/chat-panel";
import ExecutionReviewPanel from "../components/execution-review-panel";
import OllamaStatusPanel from "../components/ollama-status";
import PlannerPanel from "../components/planner-panel";
import PlanningWorkflowPanel from "../components/planning-workflow-panel";
import ReviewerPanel from "../components/reviewer-panel";
import ValidatorPanel from "../components/validator-panel";
import WorkspacePanel from "../components/workspace-panel";
import { API_DOCS_URL } from "../lib/api-config";

export default function Home() {
  return (
    <main className="min-h-screen bg-white text-zinc-950">
      <div className="mx-auto flex min-h-screen w-full max-w-5xl flex-col px-4 py-5 sm:px-6">
        <header className="flex items-center justify-between gap-4 border-b border-zinc-200 pb-4">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-zinc-950">DevLoopAI</h1>
            <p className="mt-1 text-sm text-zinc-500">
              Local AI coding assistant
            </p>
          </div>
          <a
            className="inline-flex h-9 shrink-0 items-center justify-center rounded-md border border-zinc-300 bg-white px-3 text-sm font-medium text-zinc-700 transition hover:bg-zinc-50"
            href={API_DOCS_URL}
            rel="noreferrer"
            target="_blank"
          >
            API Docs
          </a>
        </header>

        <div className="flex flex-1 flex-col justify-center py-6">
          <ChatPanel />
        </div>

        <section className="border-t border-zinc-200 py-5">
          <details className="group rounded-lg border border-zinc-200 bg-zinc-50">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-medium text-zinc-800">
              <span>System status</span>
              <span className="text-xs text-zinc-500 group-open:hidden">
                Show
              </span>
              <span className="hidden text-xs text-zinc-500 group-open:inline">
                Hide
              </span>
            </summary>
            <div className="grid grid-cols-1 gap-4 border-t border-zinc-200 p-4 lg:grid-cols-2">
              <BackendStatus />
              <OllamaStatusPanel />
            </div>
          </details>

          <details className="group mt-3 rounded-lg border border-zinc-200 bg-zinc-50">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-medium text-zinc-800">
              <span>Project and planning tools</span>
              <span className="text-xs text-zinc-500 group-open:hidden">
                Show
              </span>
              <span className="hidden text-xs text-zinc-500 group-open:inline">
                Hide
              </span>
            </summary>
            <div className="flex flex-col gap-4 border-t border-zinc-200 p-4">
              <WorkspacePanel />
              <PlannerPanel />
              <ReviewerPanel />
              <PlanningWorkflowPanel />
              <ValidatorPanel />
            </div>
          </details>

          <details className="group mt-3 rounded-lg border border-zinc-200 bg-zinc-50">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-medium text-zinc-800">
              <span>Execution review and audit</span>
              <span className="text-xs text-zinc-500 group-open:hidden">
                Show
              </span>
              <span className="hidden text-xs text-zinc-500 group-open:inline">
                Hide
              </span>
            </summary>
            <div className="border-t border-zinc-200 p-4">
              <ExecutionReviewPanel />
            </div>
          </details>
        </section>
      </div>
    </main>
  );
}
