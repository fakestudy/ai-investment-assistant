type ReasoningToggleInput = {
	isOpenBeforeToggle: boolean;
};

export function shouldReleaseChatStickinessForReasoningToggle({
	isOpenBeforeToggle,
}: ReasoningToggleInput) {
	return !isOpenBeforeToggle;
}
