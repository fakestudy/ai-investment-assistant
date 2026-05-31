import assert from "node:assert/strict";
import test from "node:test";
import {
	getVisibleMessageWindow,
	isActiveConversationStreaming,
} from "./chat-ui-state.ts";

test("isActiveConversationStreaming only locks the active conversation", () => {
	assert.equal(
		isActiveConversationStreaming({
			activeConversationId: "new-chat",
			isStreaming: true,
			streamingConversationId: "old-chat",
		}),
		false,
	);

	assert.equal(
		isActiveConversationStreaming({
			activeConversationId: undefined,
			isStreaming: true,
			streamingConversationId: "old-chat",
		}),
		false,
	);

	assert.equal(
		isActiveConversationStreaming({
			activeConversationId: "old-chat",
			isStreaming: true,
			streamingConversationId: "old-chat",
		}),
		true,
	);
});

test("getVisibleMessageWindow returns the latest bounded message slice", () => {
	const messages = Array.from({ length: 120 }, (_, index) => `message-${index}`);

	assert.deepEqual(getVisibleMessageWindow(messages, 50), {
		hiddenCount: 70,
		messages: messages.slice(70),
		startIndex: 70,
		totalCount: 120,
	});
});

test("getVisibleMessageWindow keeps all messages when the window covers them", () => {
	const messages = Array.from({ length: 20 }, (_, index) => `message-${index}`);

	assert.deepEqual(getVisibleMessageWindow(messages, 80), {
		hiddenCount: 0,
		messages,
		startIndex: 0,
		totalCount: 20,
	});
});
