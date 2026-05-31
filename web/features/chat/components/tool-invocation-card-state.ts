import type { ToolInvocation } from "../types";

export function getToolInvocationCardOpenState(
	status: ToolInvocation["status"],
) {
	return status !== "completed";
}
