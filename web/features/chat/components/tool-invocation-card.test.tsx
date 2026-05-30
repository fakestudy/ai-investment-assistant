import type { ToolInvocation } from "../types";
import { ToolInvocationCard, toToolState } from "./tool-invocation-card";

const completedInvocation: ToolInvocation = {
	id: "tool-1",
	messageId: "message-1",
	toolName: "web_search",
	args: {
		query: "latest market news",
	},
	result: {
		summary: "Found three relevant sources.",
	},
	latencyMs: 420,
	status: "completed",
};

function ToolInvocationCardTypecheck() {
	return <ToolInvocationCard invocation={completedInvocation} />;
}

const runningState = toToolState("running");
const completedState = toToolState("completed");
const errorState = toToolState("error");

export {
	completedState,
	errorState,
	runningState,
	ToolInvocationCardTypecheck,
};
