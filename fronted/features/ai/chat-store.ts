"use client";

import { useStore } from "zustand";
import { createStore } from "zustand/vanilla";
import {
  startChatStream,
  type StartChatStreamOptions,
} from "./chat-stream-client";
import type { ChatMessage, ChatStreamEvent, PageContext } from "./types";

function localID(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

type CreateId = (prefix: string) => string;

type ChatStoreDependencies = {
  startStream?: (options: StartChatStreamOptions) => Promise<void>;
  createId?: CreateId;
};

export type ChatStoreState = {
  conversationId: string;
  composerInput: string;
  error: string;
  isStreaming: boolean;
  messages: ChatMessage[];
  setComposerInput: (value: string) => void;
  clearError: () => void;
  sendMessage: (pageContext: PageContext, content?: string) => Promise<void>;
  stop: () => void;
  reset: () => void;
};

function updateAssistantMessage(
  messages: ChatMessage[],
  updater: (message: ChatMessage) => ChatMessage,
): ChatMessage[] {
  return messages.map((message) =>
    message.role === "assistant" && ["pending", "streaming"].includes(message.status)
      ? updater(message)
      : message,
  );
}

export function createChatStore({
  startStream = startChatStream,
  createId = localID,
}: ChatStoreDependencies = {}) {
  let abortController: AbortController | null = null;

  const store = createStore<ChatStoreState>((set, get) => {
    const handleEvent = (event: ChatStreamEvent) => {
      if (event.type === "metadata") {
        set((state) => ({
          ...state,
          conversationId: event.conversationId,
          messages: state.messages.map((message) =>
            message.id === "assistant-pending"
              ? { ...message, id: event.assistantMessageId, status: "streaming" }
              : message,
          ),
        }));
        return;
      }

      if (event.type === "delta") {
        set((state) => ({
          ...state,
          messages: updateAssistantMessage(state.messages, (message) => ({
            ...message,
            status: "streaming",
            content: message.content + event.content,
          })),
        }));
        return;
      }

      if (event.type === "done") {
        abortController = null;
        set((state) => ({
          ...state,
          isStreaming: false,
          messages: updateAssistantMessage(state.messages, (message) => ({
            ...message,
            status: "completed",
          })),
        }));
        return;
      }

      abortController = null;
      set((state) => ({
        ...state,
        error: event.message,
        isStreaming: false,
        messages: updateAssistantMessage(state.messages, (message) => ({
          ...message,
          status: "error",
          content: message.content || event.message,
        })),
      }));
    };

    return {
      conversationId: "",
      composerInput: "",
      error: "",
      isStreaming: false,
      messages: [],
      setComposerInput: (value) =>
        set((state) => ({ ...state, composerInput: value, error: "" })),
      clearError: () => set((state) => ({ ...state, error: "" })),
      reset: () => {
        abortController?.abort();
        abortController = null;
        set({
          conversationId: "",
          composerInput: "",
          error: "",
          isStreaming: false,
          messages: [],
          setComposerInput: get().setComposerInput,
          clearError: get().clearError,
          sendMessage: get().sendMessage,
          stop: get().stop,
          reset: get().reset,
        });
      },
      sendMessage: async (pageContext, content) => {
        if (abortController) {
          const message = "当前回答仍在生成，请先停止。";
          set((state) => ({ ...state, error: message }));
          throw new Error(message);
        }

        const trimmed = (content ?? get().composerInput).trim();
        if (!trimmed) {
          const message = "请输入问题。";
          set((state) => ({ ...state, error: message }));
          throw new Error(message);
        }

        const controller = new AbortController();
        abortController = controller;

        set((state) => ({
          ...state,
          composerInput: "",
          error: "",
          isStreaming: true,
          messages: [
            ...state.messages,
            {
              id: createId("message-user"),
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
          ],
        }));

        try {
          await startStream({
            request: {
              conversationId: get().conversationId,
              content: trimmed,
              pageContext,
            },
            token: "local-dev",
            signal: controller.signal,
            onEvent: handleEvent,
          });
        } catch (error) {
          abortController = null;

          if (!controller.signal.aborted) {
            const message = error instanceof Error ? error.message : "发送失败";
            set((state) => ({
              ...state,
              error: message,
              isStreaming: false,
              messages: updateAssistantMessage(state.messages, (chatMessage) => ({
                ...chatMessage,
                status: "error",
                content: chatMessage.content || message,
              })),
            }));
          }

          throw error;
        }
      },
      stop: () => {
        abortController?.abort();
        abortController = null;
        set((state) => ({
          ...state,
          isStreaming: false,
          messages: updateAssistantMessage(state.messages, (message) => ({
            ...message,
            status: "aborted",
          })),
        }));
      },
    };
  });

  return store;
}

export const chatStore = createChatStore();

export function useChatStore<T>(selector: (state: ChatStoreState) => T): T {
  return useStore(chatStore, selector);
}

export function resetChatStore(): void {
  chatStore.getState().reset();
}
