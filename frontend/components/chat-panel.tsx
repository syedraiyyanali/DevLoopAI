"use client";

import { FormEvent, useState } from "react";

import { ApiError, sendChatMessage } from "../lib/api-client";

type ChatState =
  | { status: "idle" }
  | { status: "sending" }
  | { status: "success"; message: string; model: string }
  | { status: "error"; message: string };

export default function ChatPanel() {
  const [message, setMessage] = useState("");
  const [chatState, setChatState] = useState<ChatState>({ status: "idle" });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedMessage = message.trim();

    if (!trimmedMessage) {
      setChatState({
        status: "error",
        message: "Enter a message before sending.",
      });
      return;
    }

    setChatState({ status: "sending" });

    try {
      const response = await sendChatMessage(trimmedMessage);

      setChatState({
        status: "success",
        message: response.message,
        model: response.model,
      });
    } catch (error: unknown) {
      const errorMessage =
        error instanceof ApiError
          ? `${error.message} HTTP status: ${error.status}.`
          : "Unable to send the chat request.";

      setChatState({
        status: "error",
        message: errorMessage,
      });
    }
  }

  const isSending = chatState.status === "sending";

  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-zinc-950">Chat</h2>
        <p className="text-sm leading-6 text-zinc-600">
          Messages go through FastAPI before reaching Ollama.
        </p>
      </div>

      <form className="mt-5 flex flex-col gap-3" onSubmit={handleSubmit}>
        <label className="sr-only" htmlFor="chat-message">
          Message
        </label>
        <textarea
          id="chat-message"
          className="min-h-28 resize-y rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm leading-6 text-zinc-950 outline-none transition focus:border-zinc-950"
          placeholder="Ask DevLoopAI something small..."
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />

        <button
          className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
          disabled={isSending}
          type="submit"
        >
          {isSending ? "Sending..." : "Send"}
        </button>
      </form>

      {chatState.status === "success" ? (
        <div className="mt-5 rounded-md border border-emerald-200 bg-emerald-50 p-4">
          <p className="text-xs font-medium uppercase text-emerald-700">
            {chatState.model}
          </p>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-emerald-950">
            {chatState.message}
          </p>
        </div>
      ) : null}

      {chatState.status === "error" ? (
        <div className="mt-5 rounded-md border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm leading-6 text-amber-900">
            {chatState.message}
          </p>
        </div>
      ) : null}
    </section>
  );
}
