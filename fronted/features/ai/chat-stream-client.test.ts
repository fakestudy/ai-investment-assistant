import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatStreamRequest } from "./types";

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: vi.fn(() => Promise.resolve()),
}));

const request: ChatStreamRequest = {
  conversationId: "",
  content: "hello",
  pageContext: {
    route: "/",
    symbol: "AAPL",
    eventId: "",
    researchCardId: "",
  },
};

describe("startChatStream", () => {
  afterEach(() => {
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    vi.clearAllMocks();
    vi.resetModules();
  });

  it("uses the local BFF default port when no API base URL is configured", async () => {
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    const { fetchEventSource } = await import("@microsoft/fetch-event-source");
    const { startChatStream } = await import("./chat-stream-client");

    await startChatStream({
      request,
      token: "token",
      signal: new AbortController().signal,
      onEvent: vi.fn(),
    });

    expect(fetchEventSource).toHaveBeenCalledWith(
      "http://localhost:8081/api/chat/stream",
      expect.objectContaining({
        method: "POST",
      }),
    );
  });
});
