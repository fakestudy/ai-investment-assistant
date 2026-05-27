import { describe, expect, it, vi } from "vitest";
import type { PageContext } from "./types";
import { createChatStore } from "./chat-store";

const pageContext: PageContext = {
  route: "/",
  symbol: "AAPL",
  eventId: "",
  researchCardId: "",
};

describe("createChatStore", () => {
  it("clears composer input after optimistic submit", async () => {
    const startStream = vi.fn().mockResolvedValue(undefined);
    const store = createChatStore({
      startStream,
      createId: (prefix) => `${prefix}-fixed`,
    });

    store.getState().setComposerInput(" 请分析 AAPL 的估值风险 ");
    await store.getState().sendMessage(pageContext);

    expect(store.getState().composerInput).toBe("");
    expect(store.getState().messages).toEqual([
      {
        id: "message-user-fixed",
        role: "user",
        content: "请分析 AAPL 的估值风险",
        status: "completed",
      },
      {
        id: "assistant-pending",
        role: "assistant",
        content: "",
        status: "pending",
      },
    ]);
    expect(startStream).toHaveBeenCalledTimes(1);
    expect(startStream.mock.calls[0]?.[0]).toMatchObject({
      request: {
        conversationId: "",
        content: "请分析 AAPL 的估值风险",
        pageContext,
      },
      token: "local-dev",
    });
    expect(startStream.mock.calls[0]?.[0]?.signal).toBeInstanceOf(AbortSignal);
  });

  it("updates stream messages from metadata, delta and done events", async () => {
    const startStream = vi.fn(async ({ onEvent }) => {
      onEvent({
        type: "metadata",
        conversationId: "conversation-1",
        userMessageId: "message-user-server-1",
        assistantMessageId: "message-assistant-1",
      });
      onEvent({ type: "delta", content: "先看营收增速，" });
      onEvent({ type: "delta", content: "再看估值与现金流。" });
      onEvent({ type: "done", finishReason: "stop" });
    });
    const store = createChatStore({
      startStream,
      createId: (prefix) => `${prefix}-fixed`,
    });

    store.getState().setComposerInput("总结一下 AAPL 关注点");
    await store.getState().sendMessage(pageContext);

    expect(store.getState().conversationId).toBe("conversation-1");
    expect(store.getState().messages).toEqual([
      {
        id: "message-user-fixed",
        role: "user",
        content: "总结一下 AAPL 关注点",
        status: "completed",
      },
      {
        id: "message-assistant-1",
        role: "assistant",
        content: "先看营收增速，再看估值与现金流。",
        status: "completed",
      },
    ]);
  });
});
