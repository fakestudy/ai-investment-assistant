import type { ApprovalBatch } from "../types";

export type ApprovalSubmissionDecision = "approve" | "reject";
export type ApprovalSelections = Record<string, ApprovalSubmissionDecision>;

export function isApprovalReadOnly(batch: ApprovalBatch) {
	return batch.status !== "pending";
}

export function canSubmitApproval(
	batch: ApprovalBatch,
	selections: ApprovalSelections,
) {
	if (isApprovalReadOnly(batch) || batch.requests.length === 0) {
		return false;
	}

	return batch.requests.every(
		(request) =>
			request.decision === "pending" &&
			(selections[request.id] === "approve" ||
				selections[request.id] === "reject"),
	);
}

export function toApprovalDecisionLabel(
	decision: ApprovalBatch["requests"][number]["decision"],
) {
	const labels: Record<ApprovalBatch["requests"][number]["decision"], string> =
		{
			pending: "等待选择",
			approved: "已批准",
			rejected: "已拒绝",
			expired: "已过期",
		};

	return labels[decision];
}
