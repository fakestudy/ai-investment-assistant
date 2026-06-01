import assert from "node:assert/strict";
import test from "node:test";
import { shouldReleaseChatStickinessForReasoningToggle } from "./chat-reasoning-scroll-state";

test("shouldReleaseChatStickinessForReasoningToggle releases only when opening reasoning", () => {
	assert.equal(
		shouldReleaseChatStickinessForReasoningToggle({
			isOpenBeforeToggle: false,
		}),
		true,
	);
	assert.equal(
		shouldReleaseChatStickinessForReasoningToggle({
			isOpenBeforeToggle: true,
		}),
		false,
	);
});
