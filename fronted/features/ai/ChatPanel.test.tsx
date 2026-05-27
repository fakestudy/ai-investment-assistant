import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetChatStore } from "./chat-store";

const { startChatStreamMock } = vi.hoisted(() => ({
  startChatStreamMock: vi.fn(),
}));

vi.mock("./chat-stream-client", () => ({
  startChatStream: startChatStreamMock,
}));

import { ChatPanel } from "./ChatPanel";

describe("ChatPanel", () => {
  beforeEach(() => {
    startChatStreamMock.mockReset();
    act(() => {
      resetChatStore();
    });
  });

  afterEach(() => {
    startChatStreamMock.mockReset();
    act(() => {
      resetChatStore();
    });
  });

  it("renders input and icon submit button", () => {
    render(<ChatPanel />);

    expect(
      screen.getByPlaceholderText("输入你想追问的股票或事件"),
    ).toBeInTheDocument();
    expect(screen.queryByText("等待提问")).not.toBeInTheDocument();
    expect(screen.queryByText("回答生成中")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送" })).toHaveTextContent("");
    expect(
      screen.queryByRole("button", { name: "停止回答" }),
    ).not.toBeInTheDocument();
  });

  it("lets the user type a question", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.type(
      screen.getByPlaceholderText("输入你想追问的股票或事件"),
      "帮我分析 AAPL 风险",
    );

    expect(screen.getByDisplayValue("帮我分析 AAPL 风险")).toBeInTheDocument();
  });

  it("clears the input immediately after optimistic submit", async () => {
    startChatStreamMock.mockResolvedValue(undefined);

    const user = userEvent.setup();
    render(<ChatPanel />);

    const input = screen.getByPlaceholderText("输入你想追问的股票或事件");

    await user.type(input, "请分析 AAPL 的估值风险");
    await user.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(screen.getByText("请分析 AAPL 的估值风险")).toBeInTheDocument();
    });

    expect(input).toHaveValue("");
  });

  it("submits the text captured by the official prompt form", async () => {
    startChatStreamMock.mockResolvedValue(undefined);

    render(<ChatPanel />);

    const input = screen.getByPlaceholderText("输入你想追问的股票或事件");
    const valueSetter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    valueSetter?.call(input, "表单里的真实问题");

    input.closest("form")?.requestSubmit();

    await waitFor(() => {
      expect(startChatStreamMock).toHaveBeenCalledWith(
        expect.objectContaining({
          request: expect.objectContaining({
            content: "表单里的真实问题",
          }),
        }),
      );
    });
  });

  it("does not block the official form submit with external composer state", () => {
    render(<ChatPanel />);

    const input = screen.getByPlaceholderText("输入你想追问的股票或事件");
    const valueSetter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    valueSetter?.call(input, "DOM 表单里的问题");

    expect(screen.getByRole("button", { name: "发送" })).toBeEnabled();
  });

  it("uses the submit button as the streaming stop control", async () => {
    startChatStreamMock.mockImplementation(
      ({ signal }) =>
        new Promise<void>((resolve) => {
          signal.addEventListener("abort", () => resolve(), { once: true });
        }),
    );

    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.type(
      screen.getByPlaceholderText("输入你想追问的股票或事件"),
      "请开始流式输出",
    );
    await user.click(screen.getByRole("button", { name: "发送" }));

    const stopButton = await screen.findByRole("button", { name: "停止回答" });
    expect(stopButton).toHaveTextContent("");
    expect(stopButton).toBeEnabled();

    await user.click(stopButton);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "发送" })).toBeEnabled();
    });
  });

  it("renders streamed assistant markdown as formatted content", async () => {
    startChatStreamMock.mockImplementation(async ({ onEvent }) => {
      onEvent({
        type: "metadata",
        conversationId: "conversation-1",
        userMessageId: "message-user-server-1",
        assistantMessageId: "message-assistant-1",
      });
      onEvent({ type: "delta", content: "**核心结论**\n\n" });
      onEvent({ type: "delta", content: "- 先看自由现金流\n" });
      onEvent({ type: "done", finishReason: "stop" });
    });

    const user = userEvent.setup();
    const { container } = render(<ChatPanel />);

    const input = screen.getByPlaceholderText("输入你想追问的股票或事件");
    await user.type(input, "请给我 markdown 格式结论");
    await user.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(container.querySelector('[data-streamdown="strong"]')).toHaveTextContent(
        "核心结论",
      );
    });
    expect(container.querySelector("li")).toHaveTextContent("先看自由现金流");
    expect(screen.queryByText("**核心结论**")).not.toBeInTheDocument();
  });
});
