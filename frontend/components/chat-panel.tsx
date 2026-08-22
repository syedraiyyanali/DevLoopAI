"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

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

const chatStorageKey = "devloopai.chatSession.v1";

const exampleMessages = [
  {
    title: "Write code",
    prompt:
      "Write clean code for this feature and explain where each file should go: ",
  },
  {
    title: "Create plugin",
    prompt:
      "Help me design and build a complete plugin. Start by asking what platform, features, files, settings, and tests are needed.",
  },
  {
    title: "Fix bug",
    prompt:
      "Help me debug this issue. Ask for the error, relevant files, expected behavior, and then propose a safe fix.",
  },
];

function loadSavedMessages(): ChatMessage[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const savedChat = window.localStorage.getItem(chatStorageKey);

    if (!savedChat) {
      return [];
    }

    const parsedMessages = JSON.parse(savedChat);

    return isValidSavedMessages(parsedMessages) ? parsedMessages : [];
  } catch {
    window.localStorage.removeItem(chatStorageKey);
    return [];
  }
}

function isValidSavedMessages(value: unknown): value is ChatMessage[] {
  if (!Array.isArray(value)) {
    return false;
  }

  return value.every(
    (item) =>
      typeof item === "object" &&
      item !== null &&
      typeof (item as ChatMessage).id === "number" &&
      ((item as ChatMessage).role === "user" ||
        (item as ChatMessage).role === "assistant") &&
      typeof (item as ChatMessage).content === "string" &&
      ((item as ChatMessage).model === undefined ||
        typeof (item as ChatMessage).model === "string"),
  );
}

export default function ChatPanel() {
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>(loadSavedMessages);
  const [chatStatus, setChatStatus] = useState<ChatStatus>({ status: "idle" });

  const nextMessageId = useMemo(
    () =>
      messages.reduce(
        (highestId, chatMessage) => Math.max(highestId, chatMessage.id),
        0,
      ) + 1,
    [messages],
  );
  const isSending = chatStatus.status === "sending";
  const canSend = message.trim().length > 0 && !isSending;

  useEffect(() => {
    if (typeof window === "undefined" || isSending) {
      return;
    }

    if (messages.length === 0) {
      window.localStorage.removeItem(chatStorageKey);
      return;
    }

    window.localStorage.setItem(chatStorageKey, JSON.stringify(messages));
  }, [isSending, messages]);

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
    window.localStorage.removeItem(chatStorageKey);
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
    <section className="mx-auto flex w-full max-w-3xl flex-col">
      <div className="flex min-h-11 items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2 className="text-sm font-medium text-zinc-500">Chat</h2>
          <p className="text-xs text-zinc-400">
            Current chat saves automatically in this browser.
          </p>
        </div>

        <button
          className="inline-flex h-9 w-fit items-center justify-center rounded-md px-3 text-sm font-medium text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-950 disabled:hidden"
          disabled={messages.length === 0 || isSending}
          onClick={clearConversation}
          type="button"
        >
          Clear
        </button>
      </div>

      <div className="mt-4 min-h-[360px]">
        {messages.length === 0 ? (
          <div className="flex min-h-[360px] flex-col items-center justify-center gap-6 text-center">
            <div>
              <p className="text-2xl font-semibold text-zinc-950 sm:text-3xl">
                What do you want to build?
              </p>
              <p className="mt-3 text-sm leading-6 text-zinc-500">
                Ask DevLoopAI a question or start with one of these prompts.
              </p>
            </div>
            <div className="grid w-full max-w-2xl grid-cols-1 gap-2 sm:grid-cols-3">
              {exampleMessages.map((exampleMessage) => (
                <button
                  className="rounded-lg border border-zinc-200 bg-white px-3 py-3 text-left text-sm text-zinc-700 transition hover:border-zinc-300 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:text-zinc-400"
                  disabled={isSending}
                  key={exampleMessage.title}
                  onClick={() => selectExample(exampleMessage.prompt)}
                  type="button"
                >
                  <span className="block font-medium text-zinc-950">
                    {exampleMessage.title}
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-zinc-500">
                    {exampleMessage.prompt}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ol className="flex flex-col gap-5">
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
                  className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                    chatMessage.role === "user"
                      ? "bg-zinc-950 text-white"
                      : "bg-zinc-100 text-zinc-950"
                  }`}
                >
                  <p
                    className={`text-xs font-medium ${
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
                <div className="rounded-2xl bg-zinc-100 px-4 py-3 text-sm text-zinc-600">
                  Thinking...
                </div>
              </li>
            ) : null}
          </ol>
        )}
      </div>

      {chatStatus.status === "error" ? (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm leading-6 text-amber-900">
            {chatStatus.message}
          </p>
        </div>
      ) : null}

      <form
        className="mt-5 rounded-2xl border border-zinc-200 bg-white p-2 shadow-sm"
        onSubmit={handleSubmit}
      >
        <label className="sr-only" htmlFor="chat-message">
          Message
        </label>
        <textarea
          id="chat-message"
          className="min-h-24 w-full resize-none rounded-xl border-0 bg-white px-3 py-3 text-sm leading-6 text-zinc-950 outline-none disabled:cursor-not-allowed disabled:bg-zinc-100"
          disabled={isSending}
          placeholder="Message DevLoopAI..."
          value={message}
          onChange={(event) => {
            setMessage(event.target.value);
            if (chatStatus.status === "error") {
              setChatStatus({ status: "idle" });
            }
          }}
        />

        <div className="flex items-center justify-between gap-3 px-2 pb-1">
          <p className="text-xs text-zinc-400">
            Saved chat - Local Ollama via FastAPI
          </p>
          <button
            className="inline-flex h-9 w-fit items-center justify-center rounded-lg bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-300"
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
