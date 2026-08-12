"use client";

import { FormEvent, useMemo, useState } from "react";

import {
  ApiError,
  sendChatMessage,
  streamChatMessage,
} from "../lib/api-client";

type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  model?: string;
};

type ChatStatus =
  | { status: "idle" }
  | { status: "sending" }
  | { status: "error"; message: string };

const exampleMessages = [
  "Confirm DevLoopAI is connected.",
  "Explain what this backend can do so far.",
  "Give me a tiny HTML button example.",
];

export default function ChatPanel() {
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatStatus, setChatStatus] = useState<ChatStatus>({ status: "idle" });

  const nextMessageId = useMemo(() => messages.length + 1, [messages.length]);
  const isSending = chatStatus.status === "sending";
  const canSend = message.trim().length > 0 && !isSending;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedMessage = message.trim();

    if (!trimmedMessage) {
      setChatStatus({
        status: "error",
        message: "Enter a message before sending.",
      });
      return;
    }

    const userMessage: ChatMessage = {
      id: nextMessageId,
      role: "user",
      content: trimmedMessage,
    };
    const assistantMessageId = nextMessageId + 1;
    const assistantMessage: ChatMessage = {
      id: assistantMessageId,
      role: "assistant",
      content: "",
      model: "qwen2.5-coder:7b",
    };

    setMessages((currentMessages) => [
      ...currentMessages,
      userMessage,
      assistantMessage,
    ]);
    setMessage("");
    setChatStatus({ status: "sending" });
    let receivedStreamingContent = false;

    try {
      await streamChatMessage(trimmedMessage, (chunk) => {
        receivedStreamingContent = true;
        appendAssistantChunk(assistantMessageId, chunk);
      });

      if (!receivedStreamingContent) {
        await completeWithFallback(trimmedMessage, assistantMessageId);
      }

      setChatStatus({ status: "idle" });
    } catch (error: unknown) {
      if (!receivedStreamingContent) {
        try {
          await completeWithFallback(trimmedMessage, assistantMessageId);
          setChatStatus({ status: "idle" });
          return;
        } catch (fallbackError: unknown) {
          setChatStatus({
            status: "error",
            message: getChatErrorMessage(fallbackError),
          });
          return;
        }
      }

      const errorMessage =
        error instanceof Error
          ? `Stream interrupted: ${error.message}`
          : "Stream interrupted before completion.";

      setChatStatus({
        status: "error",
        message: errorMessage,
      });
    }
  }

  function selectExample(exampleMessage: string) {
    if (isSending) {
      return;
    }

    setMessage(exampleMessage);
    setChatStatus({ status: "idle" });
  }

  function clearConversation() {
    if (isSending) {
      return;
    }

    setMessages([]);
    setMessage("");
    setChatStatus({ status: "idle" });
  }

  function appendAssistantChunk(assistantMessageId: number, chunk: string) {
    setMessages((currentMessages) =>
      currentMessages.map((chatMessage) =>
        chatMessage.id === assistantMessageId
          ? {
              ...chatMessage,
              content: `${chatMessage.content}${chunk}`,
            }
          : chatMessage,
      ),
    );
  }

  async function completeWithFallback(
    trimmedMessage: string,
    assistantMessageId: number,
  ) {
    const response = await sendChatMessage(trimmedMessage);

    setMessages((currentMessages) =>
      currentMessages.map((chatMessage) =>
        chatMessage.id === assistantMessageId
          ? {
              ...chatMessage,
              content: response.message,
              model: response.model,
            }
          : chatMessage,
      ),
    );
  }

  function getChatErrorMessage(error: unknown): string {
    if (error instanceof ApiError) {
      return `${error.message} HTTP status: ${error.status}.`;
    }

    if (error instanceof Error) {
      return error.message;
    }

    return "Unable to send the chat request.";
  }

  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex flex-col gap-1">
          <h2 className="text-base font-semibold text-zinc-950">Chat</h2>
          <p className="text-sm leading-6 text-zinc-600">
            Messages go through FastAPI before reaching Ollama.
          </p>
        </div>

        <button
          className="inline-flex h-9 w-fit items-center justify-center rounded-md border border-zinc-300 bg-white px-3 text-sm font-medium text-zinc-700 transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:text-zinc-400"
          disabled={messages.length === 0 || isSending}
          onClick={clearConversation}
          type="button"
        >
          Clear
        </button>
      </div>

      <div className="mt-5 min-h-64 rounded-md border border-zinc-200 bg-zinc-50 p-4">
        {messages.length === 0 ? (
          <div className="flex min-h-56 flex-col justify-center gap-3 text-sm text-zinc-600">
            <p className="font-medium text-zinc-800">No messages yet.</p>
            <div className="flex flex-wrap gap-2">
              {exampleMessages.map((exampleMessage) => (
                <button
                  className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-left text-sm text-zinc-700 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:text-zinc-400"
                  disabled={isSending}
                  key={exampleMessage}
                  onClick={() => selectExample(exampleMessage)}
                  type="button"
                >
                  {exampleMessage}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ol className="flex flex-col gap-3">
            {messages.map((chatMessage) => (
              <li
                className={`flex ${
                  chatMessage.role === "user"
                    ? "justify-end"
                    : "justify-start"
                }`}
                key={chatMessage.id}
              >
                <div
                  className={`max-w-3xl rounded-lg border p-4 ${
                    chatMessage.role === "user"
                      ? "border-zinc-900 bg-zinc-950 text-white"
                      : "border-zinc-200 bg-white text-zinc-950"
                  }`}
                >
                  <p
                    className={`text-xs font-medium uppercase ${
                      chatMessage.role === "user"
                        ? "text-zinc-300"
                        : "text-zinc-500"
                    }`}
                  >
                    {chatMessage.role === "user"
                      ? "You"
                      : chatMessage.model ?? "DevLoopAI"}
                  </p>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
                    {chatMessage.content}
                  </p>
                </div>
              </li>
            ))}

            {isSending && messages[messages.length - 1]?.content === "" ? (
              <li className="flex justify-start">
                <div className="rounded-lg border border-zinc-200 bg-white p-4 text-sm text-zinc-600">
                  Connecting to stream...
                </div>
              </li>
            ) : null}
          </ol>
        )}
      </div>

      {chatStatus.status === "error" ? (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm leading-6 text-amber-900">
            {chatStatus.message}
          </p>
        </div>
      ) : null}

      <form className="mt-5 flex flex-col gap-3" onSubmit={handleSubmit}>
        <label className="sr-only" htmlFor="chat-message">
          Message
        </label>
        <textarea
          id="chat-message"
          className="min-h-28 resize-y rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm leading-6 text-zinc-950 outline-none transition focus:border-zinc-950 disabled:cursor-not-allowed disabled:bg-zinc-100"
          disabled={isSending}
          placeholder="Ask DevLoopAI something small..."
          value={message}
          onChange={(event) => {
            setMessage(event.target.value);
            if (chatStatus.status === "error") {
              setChatStatus({ status: "idle" });
            }
          }}
        />

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-zinc-500">
            Streaming chat is active; non-streaming fallback remains available.
          </p>
          <button
            className="inline-flex h-10 w-fit items-center justify-center rounded-md bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
            disabled={!canSend}
            type="submit"
          >
            {isSending ? "Sending..." : "Send"}
          </button>
        </div>
      </form>
    </section>
  );
}
