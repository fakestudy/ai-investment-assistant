import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { ApprovalCard } from "./approval-card";

test("approval decisions render as named radio groups", () => {
	const markup = renderToStaticMarkup(
		<ApprovalCard
			batch={{
				id: "batch-a11y",
				status: "pending",
				expiresAt: "2026-06-07T12:30:00.000Z",
				requests: [
					{
						id: "request-1",
						toolInvocationId: "tool-1",
						toolName: "get_weather",
						args: { city: "Beijing" },
						decision: "pending",
					},
				],
			}}
			conversationId="conversation-1"
		/>,
	);

	assert.match(markup, /<fieldset/);
	assert.match(markup, /<legend[^>]*>工具：get_weather<\/legend>/);
	assert.match(markup, /type="radio"/);
	assert.match(markup, /name="approval-request-1"/);
	assert.match(markup, /value="approve"/);
	assert.match(markup, /value="reject"/);
});
