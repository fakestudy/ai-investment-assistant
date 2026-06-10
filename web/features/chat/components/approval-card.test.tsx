import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { ApprovalCard } from "./approval-card";

test("approval decisions render as direct action buttons", () => {
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
	assert.match(markup, /data-decision-layout="inline"/);
	assert.match(markup, /data-approval-option="approve"/);
	assert.match(markup, /data-approval-option="reject"/);
	assert.match(
		markup,
		/<button[^>]+data-approval-option="approve"[^>]+type="button"/,
	);
	assert.match(
		markup,
		/<button[^>]+data-approval-option="reject"[^>]+type="button"/,
	);
	assert.doesNotMatch(markup, /type="radio"/);
	assert.doesNotMatch(markup, /提交审批/);
	assert.ok(
		markup.indexOf("</pre>") < markup.indexOf('data-approval-option="approve"'),
	);
});

test("floating approval card renders compact overlay variant", () => {
	const markup = renderToStaticMarkup(
		<ApprovalCard
			batch={{
				id: "batch-floating",
				status: "pending",
				expiresAt: "2026-06-07T12:30:00.000Z",
				requests: [
					{
						id: "request-1",
						toolInvocationId: "tool-1",
						toolName: "WebSearch",
						args: { query: "北京天气预报 2026年6月" },
						decision: "pending",
					},
				],
			}}
			conversationId="conversation-1"
			variant="floating"
		/>,
	);

	assert.match(markup, /data-variant="floating"/);
	assert.match(markup, /待审批工具/);
	assert.match(markup, /WebSearch/);
	assert.match(markup, /北京天气预报 2026年6月/);
	assert.match(markup, /data-decision-layout="banner"/);
	assert.match(markup, /data-approval-option="approve"/);
	assert.match(markup, /data-approval-option="reject"/);
	assert.match(
		markup,
		/<button[^>]+data-approval-option="approve"[^>]+type="button"/,
	);
	assert.match(
		markup,
		/<button[^>]+data-approval-option="reject"[^>]+type="button"/,
	);
	assert.doesNotMatch(markup, /type="radio"/);
	assert.doesNotMatch(markup, /提交审批/);
	assert.ok(
		markup.indexOf("</pre>") < markup.indexOf('data-approval-option="approve"'),
	);
});
