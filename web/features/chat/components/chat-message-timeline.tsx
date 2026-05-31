"use client";

import { BrainIcon, ListTreeIcon, WrenchIcon } from "lucide-react";
import { ChainOfThoughtStep } from "@/components/ai-elements/chain-of-thought";
import {
	Reasoning,
	ReasoningContent,
	ReasoningTrigger,
} from "@/components/ai-elements/reasoning";
import type { ChatMessage, ChatTimelinePart } from "../types";
import { ToolInvocationCard } from "./tool-invocation-card";

type ChatMessageTimelineProps = {
	message: ChatMessage;
	isStreaming: boolean;
};

function getTimelineParts(message: ChatMessage): ChatTimelinePart[] {
	if (message.timelineParts?.length) {
		return [...message.timelineParts].sort(
			(first, second) => (first.orderIndex ?? 0) - (second.orderIndex ?? 0),
		);
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
			<ReasoningTrigger icon={<ListTreeIcon className="size-4" />} />
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
