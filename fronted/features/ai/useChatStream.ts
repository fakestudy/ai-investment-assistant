"use client";

import { useRef, useState } from "react";
import { startChatStream } from "./chat-stream-client";
import type { ChatMessage, ChatStreamEvent, PageContext } from "./types";

function localID(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

export function useChatStream() {
  const [conversationId, setConversationId] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const handleEvent = (event: ChatStreamEvent) => {
    if (event.type === "metadata") {
      setConversationId(event.conversationId);
      setMessages((current) =>
        current.map((message) =>
          message.id === "assistant-pending"
            ? { ...message, id: event.assistantMessageId, status: "streaming" }
            : message,
        ),
      );
      return;
    }
    if (event.type === "delta") {
      setMessages((current) =>
        current.map((message) =>
          message.role === "assistant" && message.status === "streaming"
            ? { ...message, content: message.content + event.content }
            : message,
        ),
      );
      return;
    }
    if (event.type === "done") {
      setMessages((current) =>
        current.map((message) =>
          message.role === "assistant" && message.status === "streaming"
            ? { ...message, status: "completed" }
            : message,
        ),
      );
      abortRef.current = null;
      return;
    }
    setMessages((current) =>
      current.map((message) =>
        message.role === "assistant" && message.status === "streaming"
          ? {
              ...message,
              status: "error",
              content: message.content || event.message,
            }
          : message,
      ),
    );
    abortRef.current = null;
  };

  const sendMessage = async (content: string, pageContext: PageContext) => {
    if (abortRef.current) {
      throw new Error("当前回答仍在生成，请先停止。");
    }
    const trimmed = content.trim();
    if (!trimmed) {
      throw new Error("请输入问题。");
    }

    const controller = new AbortController();
    abortRef.current = controller;
    setMessages((current) => [
      ...current,
      {
        id: localID("message-user"),
        role: "user",
        content: trimmed,
        status: "completed",
      },
      {
        id: "assistant-pending",
        role: "assistant",
        content: "",
        status: "pending",
      },
    ]);

    try {
      await startChatStream({
        request: { conversationId, content: trimmed, pageContext },
        token: "local-dev",
        signal: controller.signal,
        onEvent: handleEvent,
      });
    } catch (err) {
      abortRef.current = null;
      if (!controller.signal.aborted) {
        const message = err instanceof Error ? err.message : "发送失败";
        setMessages((current) =>
          current.map((chatMessage) =>
            chatMessage.role === "assistant" &&
            ["pending", "streaming"].includes(chatMessage.status)
              ? {
                  ...chatMessage,
                  status: "error",
                  content: chatMessage.content || message,
                }
              : chatMessage,
          ),
        );
      }
      throw err;
    }
  };

  const stop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setMessages((current) =>
      current.map((message) =>
        message.role === "assistant" &&
        ["pending", "streaming"].includes(message.status)
          ? { ...message, status: "aborted" }
          : message,
      ),
    );
  };

  return { conversationId, messages, sendMessage, stop };
}
