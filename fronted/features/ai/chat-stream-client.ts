import { fetchEventSource } from "@microsoft/fetch-event-source";
import { parseChatStreamEvent } from "./chat-event-parser";
import type { ChatStreamEvent, ChatStreamRequest } from "./types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

export type StartChatStreamOptions = {
  request: ChatStreamRequest;
  token: string;
  signal: AbortSignal;
  onEvent: (event: ChatStreamEvent) => void;
};

export async function startChatStream({
  request,
  token,
  signal,
  onEvent,
}: StartChatStreamOptions): Promise<void> {
  await fetchEventSource(`${API_BASE_URL}/api/chat/stream`, {
    method: "POST",
    headers: {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(request),
    signal,
    onmessage(message) {
      const payload =
        message.data.trim() === ""
          ? {}
          : (JSON.parse(message.data) as Record<string, unknown>);
      onEvent(parseChatStreamEvent(message.event, payload));
    },
  });
}
