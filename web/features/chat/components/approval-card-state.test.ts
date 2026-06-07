import assert from "node:assert/strict";
import test from "node:test";
import type { ApprovalBatch } from "../types";
import {
	type ApprovalSelections,
	canSubmitApproval,
	isApprovalReadOnly,
} from "./approval-card-state";

const pendingBatch: ApprovalBatch = {
	id: "batch-1",
	status: "pending",
	expiresAt: "2026-06-07T12:30:00.000Z",
	requests: [
		{
			id: "r1",
			toolInvocationId: "tool-1",
			toolName: "get_weather",
			args: { city: "Beijing" },
			decision: "pending",
		},
		{
			id: "r2",
			toolInvocationId: "tool-2",
			toolName: "get_weather",
			args: { city: "Shanghai" },
			decision: "pending",
		},
	],
};

const resolvedBatch: ApprovalBatch = {
	...pendingBatch,
	status: "resolved",
	resolutionSource: "manual",
	resolvedAt: "2026-06-07T12:02:00.000Z",
	requests: pendingBatch.requests.map((request) => ({
		...request,
		decision: "approved",
		decidedAt: "2026-06-07T12:02:00.000Z",
	})),
};

const expiredBatch: ApprovalBatch = {
	...pendingBatch,
	status: "expired",
	resolutionSource: "timeout",
	resolvedAt: "2026-06-07T12:30:00.000Z",
	requests: pendingBatch.requests.map((request) => ({
		...request,
		decision: "expired",
		decidedAt: "2026-06-07T12:30:00.000Z",
	})),
};

test("submit stays disabled until every request is selected", () => {
	assert.equal(canSubmitApproval(pendingBatch, { r1: "approve" }), false);
	assert.equal(
		canSubmitApproval(pendingBatch, { r1: "approve", r2: "reject" }),
		true,
	);
});

test("resolved and expired batches are read only", () => {
	assert.equal(isApprovalReadOnly(resolvedBatch), true);
	assert.equal(isApprovalReadOnly(expiredBatch), true);
	assert.equal(isApprovalReadOnly(pendingBatch), false);
});

test("submit ignores unknown selections and read only batches", () => {
	const selections: ApprovalSelections = {
		r1: "approve",
		r2: "reject",
		foreign: "approve",
	};

	assert.equal(canSubmitApproval(resolvedBatch, selections), false);
	assert.equal(canSubmitApproval(expiredBatch, selections), false);
});
