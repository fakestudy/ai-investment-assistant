import { describe, expect, it } from "vitest";
import { parseChatStreamEvent } from "./chat-event-parser";

describe("parseChatStreamEvent", () => {
  it("parses metadata events", () => {
    expect(
      parseChatStreamEvent("metadata", {
        conversationId: "conversation-1",
        userMessageId: "message-user-1",
        assistantMessageId: "message-assistant-1",
      }),
    ).toEqual({
      type: "metadata",
      conversationId: "conversation-1",
      userMessageId: "message-user-1",
      assistantMessageId: "message-assistant-1",
    });
  });

  it("parses delta events", () => {
    expect(parseChatStreamEvent("delta", { content: "hello" })).toEqual({
      type: "delta",
      content: "hello",
    });
  });

  it("parses error events", () => {
    expect(
      parseChatStreamEvent("error", {
        code: "AGENT_UNAVAILABLE",
        message: "Agent service is unavailable",
      }),
    ).toEqual({
      type: "error",
      code: "AGENT_UNAVAILABLE",
      message: "Agent service is unavailable",
    });
  });
});
