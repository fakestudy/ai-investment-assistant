import type { ChatStreamEvent } from "./types";

type EventPayload = Record<string, unknown>;

function readString(payload: EventPayload, key: string): string {
  const value = payload[key];
  return typeof value === "string" ? value : "";
}

export function parseChatStreamEvent(
  eventName: string,
  payload: EventPayload,
): ChatStreamEvent {
  if (eventName === "metadata") {
    return {
      type: "metadata",
      conversationId: readString(payload, "conversationId"),
      userMessageId: readString(payload, "userMessageId"),
      assistantMessageId: readString(payload, "assistantMessageId"),
    };
  }
  if (eventName === "delta") {
    return { type: "delta", content: readString(payload, "content") };
  }
  if (eventName === "done") {
    return { type: "done", finishReason: readString(payload, "finishReason") };
  }
  if (eventName === "error") {
    return {
      type: "error",
      code: readString(payload, "code"),
      message: readString(payload, "message"),
    };
  }
  return {
    type: "error",
    code: "UNKNOWN_STREAM_EVENT",
    message: `Unknown stream event: ${eventName}`,
  };
}
