import assert from "node:assert/strict";
import test from "node:test";
import {
	getToolInvocationCardOpenState,
	getToolInvocationStatusSummary,
} from "./tool-invocation-card-state";

test("getToolInvocationCardOpenState keeps active tool calls expanded", () => {
	assert.equal(getToolInvocationCardOpenState("running"), true);
	assert.equal(getToolInvocationCardOpenState("error"), true);
});

test("getToolInvocationCardOpenState collapses completed tool calls", () => {
	assert.equal(getToolInvocationCardOpenState("completed"), false);
});

test("getToolInvocationStatusSummary explains approval terminal states", () => {
	assert.equal(
		getToolInvocationStatusSummary("awaiting_approval"),
		"等待人工审批后执行",
	);
	assert.equal(getToolInvocationStatusSummary("rejected"), "用户已拒绝执行");
	assert.equal(
		getToolInvocationStatusSummary("expired"),
		"审批超时，系统已自动拒绝执行",
	);
});
