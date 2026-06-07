import type { ToolInvocation } from "../types";

export function getToolInvocationCardOpenState(
	status: ToolInvocation["status"],
) {
	return status !== "completed";
}

export function getToolInvocationStatusSummary(
	status: ToolInvocation["status"],
) {
	const summaries: Record<ToolInvocation["status"], string> = {
		running: "正在执行工具",
		completed: "工具执行完成",
		error: "工具执行失败",
		awaiting_approval: "等待人工审批后执行",
		rejected: "用户已拒绝执行",
		expired: "审批超时，系统已自动拒绝执行",
	};

	return summaries[status];
}
