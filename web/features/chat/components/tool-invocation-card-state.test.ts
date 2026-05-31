import assert from "node:assert/strict";
import test from "node:test";
import { getToolInvocationCardOpenState } from "./tool-invocation-card-state";

test("getToolInvocationCardOpenState keeps active tool calls expanded", () => {
	assert.equal(getToolInvocationCardOpenState("running"), true);
	assert.equal(getToolInvocationCardOpenState("error"), true);
});

test("getToolInvocationCardOpenState collapses completed tool calls", () => {
	assert.equal(getToolInvocationCardOpenState("completed"), false);
});
