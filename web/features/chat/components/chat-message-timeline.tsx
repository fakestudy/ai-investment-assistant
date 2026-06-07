"use client";

import {
	BrainIcon,
	CheckCircleIcon,
	ListTreeIcon,
	ShieldIcon,
	WrenchIcon,
	XCircleIcon,
} from "lucide-react";
import { useCallback } from "react";
import { useStickToBottomContext } from "use-stick-to-bottom";
import { ChainOfThoughtStep } from "@/components/ai-elements/chain-of-thought";
import {
	Reasoning,
	ReasoningContent,
	ReasoningTrigger,
	useReasoning,
} from "@/components/ai-elements/reasoning";
import { getRenderableTimelineParts } from "../chat-ui-state";
import type { ChatMessage, ChatTimelinePart } from "../types";
import { shouldReleaseChatStickinessForReasoningToggle } from "./chat-reasoning-scroll-state";
import { ToolInvocationCard } from "./tool-invocation-card";

type ChatMessageTimelineProps = {
	message: ChatMessage;
	isStreaming: boolean;
};

function getTimelineParts(message: ChatMessage): ChatTimelinePart[] {
	if (message.timelineParts?.length) {
		return getRenderableTimelineParts(message.timelineParts);
	}

	const parts: ChatTimelinePart[] = [];
	if (message.reasoning) {
		parts.push({
			id: `${message.id}-reasoning`,
			type: "reasoning",
			text: message.reasoning,
		});
	}

	for (const invocation of message.toolInvocations ?? []) {
		parts.push({
			id: invocation.id,
			type: "tool",
			invocation,
		});
	}

	return parts;
}

function getApprovalTimelineLabel(
	part: Extract<ChatTimelinePart, { type: "approval" }>,
) {
	const requestedTools = part.batch.requests
		.map((request) => request.toolName)
		.join(", ");
	const status =
		part.batch.status === "pending"
			? "Awaiting approval"
			: part.batch.status === "expired"
				? "Approval expired"
				: "Approval resolved";

	return (
		<div className="space-y-1">
			<p className="font-medium text-foreground">{status}</p>
			{requestedTools ? (
				<p className="text-muted-foreground">Tools: {requestedTools}</p>
			) : null}
		</div>
	);
}

export function hasTimelineDetails(message: ChatMessage) {
	return Boolean(
		message.timelineParts?.length ||
			message.reasoning ||
			message.toolInvocations?.length,
	);
}

export function ChatMessageTimeline({
	message,
	isStreaming,
}: ChatMessageTimelineProps) {
	const parts = getTimelineParts(message);

	if (parts.length === 0) {
		return null;
	}

	return (
		<Reasoning isStreaming={isStreaming}>
			<ChatReasoningTrigger />
			<ReasoningContent>
				<div className="space-y-3">
					{parts.map((part) =>
						part.type === "reasoning" ? (
							<ChainOfThoughtStep
								icon={BrainIcon}
								key={part.id}
								label={
									<p className="whitespace-pre-wrap text-muted-foreground">
										{part.text}
									</p>
								}
							/>
						) : part.type === "approval" ? (
							<ChainOfThoughtStep
								icon={
									part.batch.status === "pending"
										? ShieldIcon
										: part.batch.status === "expired"
											? XCircleIcon
											: CheckCircleIcon
								}
								key={part.id}
								label={getApprovalTimelineLabel(part)}
							/>
						) : (
							<ChainOfThoughtStep
								icon={WrenchIcon}
								key={part.id}
								label={part.invocation.toolName}
							>
								<ToolInvocationCard
									hideHeaderIcon
									invocation={part.invocation}
								/>
							</ChainOfThoughtStep>
						),
					)}
				</div>
			</ReasoningContent>
		</Reasoning>
	);
}

function ChatReasoningTrigger() {
	const { isOpen } = useReasoning();
	const { stopScroll } = useStickToBottomContext();

	const releaseStickinessBeforeOpening = useCallback(() => {
		if (
			shouldReleaseChatStickinessForReasoningToggle({
				isOpenBeforeToggle: isOpen,
			})
		) {
			stopScroll();
		}
	}, [isOpen, stopScroll]);

	return (
		<ReasoningTrigger
			icon={<ListTreeIcon className="size-4" />}
			onClickCapture={releaseStickinessBeforeOpening}
		/>
	);
}
