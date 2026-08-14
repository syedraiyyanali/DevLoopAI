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
    <main className="min-h-screen bg-zinc-100 px-4 py-6 text-zinc-950 sm:px-6 lg:px-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
        <header className="flex flex-col gap-2 border-b border-zinc-200 pb-6">
          <p className="text-sm font-medium uppercase tracking-wide text-zinc-500">
            Local AI development platform
          </p>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h1 className="text-3xl font-semibold text-zinc-950">
                DevLoopAI
              </h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-600">
                Backend status, Ollama connectivity, and the first chat path are
                wired through FastAPI.
              </p>
            </div>
            <a
              className="inline-flex h-10 w-fit items-center justify-center rounded-md border border-zinc-300 bg-white px-4 text-sm font-medium text-zinc-950 transition hover:bg-zinc-50"
              href={API_DOCS_URL}
              rel="noreferrer"
              target="_blank"
            >
              API Docs
            </a>
          </div>
        </header>

        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <BackendStatus />
          <OllamaStatusPanel />
        </section>

        <WorkspacePanel />

        <PlannerPanel />

        <ReviewerPanel />

        <PlanningWorkflowPanel />

        <ExecutionReviewPanel />

        <ValidatorPanel />

        <ChatPanel />
      </div>
    </main>
  );
}
