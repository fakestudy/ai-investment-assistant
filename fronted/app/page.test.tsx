import { render, screen } from "@testing-library/react";
import Home from "./page";

describe("Home", () => {
  it("renders the AI investment assistant shell", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", { name: "AI 投资助手" }),
    ).toBeInTheDocument();
    expect(screen.getByText("非投资建议，仅供研究参考")).toBeInTheDocument();
  });
});
