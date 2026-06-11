"use client";

import {
	FileTextIcon,
	Globe2Icon,
	LinkIcon,
	ListTreeIcon,
	SearchIcon,
	WrenchIcon,
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
import {
	getRenderableTimelineItems,
	getRenderableTimelineParts,
} from "../chat-ui-state";
import type { ChatMessage, RunTimelineItem, ToolInvocation } from "../types";
import { shouldReleaseChatStickinessForReasoningToggle } from "./chat-reasoning-scroll-state";

type ChatMessageTimelineProps = {
	message: ChatMessage;
	isStreaming: boolean;
};

function getTimelineItems(message: ChatMessage): RunTimelineItem[] {
	if (message.timelineItems?.length) {
		return getRenderableTimelineItems(message.timelineItems);
	}

	if (message.timelineParts?.length) {
		const legacyItems: RunTimelineItem[] = getRenderableTimelineParts(
			message.timelineParts,
		).flatMap<RunTimelineItem>((part) => {
			if (part.type === "reasoning") {
				return [
					{
						id: part.id,
						type: "thought" as const,
						orderIndex: part.orderIndex,
						text: part.text,
					},
				];
			}
			if (part.type === "tool") {
				return [
					{
						id: part.id,
						type: "tool" as const,
						orderIndex: part.orderIndex,
						invocation: part.invocation,
					},
				];
			}
			return [];
		});
		if (legacyItems.length > 0) {
			return legacyItems;
		}
	}

	const items: RunTimelineItem[] = [];
	if (message.reasoning) {
		items.push({
			id: `${message.id}-reasoning`,
			type: "thought",
			text: message.reasoning,
		});
	}

	for (const invocation of message.toolInvocations ?? []) {
		items.push({
			id: invocation.id,
			type: "tool",
			invocation,
		});
	}

	return items;
}

function getToolIcon(toolName: string) {
	const normalizedName = toolName.toLowerCase();
	if (normalizedName.includes("search")) {
		return SearchIcon;
	}
	if (normalizedName.includes("fetch") || normalizedName.includes("url")) {
		return LinkIcon;
	}
	if (normalizedName.includes("web")) {
		return Globe2Icon;
	}
	if (normalizedName.includes("file") || normalizedName.includes("read")) {
		return FileTextIcon;
	}
	return WrenchIcon;
}

const toolStatusText: Record<ToolInvocation["status"], string> = {
	running: "运行中",
	completed: "完成",
	error: "失败",
	awaiting_approval: "等待审批",
	rejected: "已拒绝",
	expired: "已过期",
};

function formatToolArgs(args: Record<string, unknown>) {
	return JSON.stringify(args);
}

function ToolTimelineLabel({
	item,
}: {
	item: Extract<RunTimelineItem, { type: "tool" }>;
}) {
	return (
		<div className="min-w-0 space-y-2">
			<div className="flex flex-wrap items-center gap-2">
				<span className="font-medium text-foreground">
					{item.invocation.toolName}
				</span>
				<span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-600">
					{toolStatusText[item.invocation.status]}
				</span>
			</div>
			<div className="max-w-full overflow-x-auto rounded-lg bg-zinc-50 px-3 py-2 font-mono text-[12px] text-zinc-600">
				{formatToolArgs(item.invocation.args)}
			</div>
			{item.invocation.error ? (
				<p className="text-red-600 text-xs">{item.invocation.error}</p>
			) : null}
		</div>
	);
}

export function hasTimelineDetails(message: ChatMessage) {
	return Boolean(
		message.timelineItems?.length ||
			message.timelineParts?.some((part) => part.type !== "approval") ||
			message.reasoning ||
			message.toolInvocations?.length,
	);
}

export function ChatMessageTimeline({
	message,
	isStreaming,
}: ChatMessageTimelineProps) {
	const items = getTimelineItems(message);

	if (items.length === 0) {
		return null;
	}

	return (
		<Reasoning isStreaming={isStreaming}>
			<ChatReasoningTrigger />
			<ReasoningContent>
				<div className="space-y-3">
					{items.map((item) =>
						item.type === "thought" ? (
							<p
								className="whitespace-pre-wrap text-muted-foreground text-sm"
								key={item.id}
							>
								{item.text}
							</p>
						) : (
							<ChainOfThoughtStep
								icon={getToolIcon(item.invocation.toolName)}
								key={item.id}
								label={<ToolTimelineLabel item={item} />}
							/>
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
