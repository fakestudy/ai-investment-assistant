import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ChatPanel } from "./ChatPanel";

describe("ChatPanel", () => {
  it("renders input and action buttons", () => {
    render(<ChatPanel />);

    expect(
      screen.getByPlaceholderText("输入你想追问的股票或事件"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "停止回答" }),
    ).toBeInTheDocument();
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
});
