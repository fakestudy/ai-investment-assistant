"use client";

import {
	CheckIcon,
	CopyIcon,
	PencilIcon,
	RotateCcwIcon,
	ThumbsDownIcon,
	ThumbsUpIcon,
	XIcon,
} from "lucide-react";
import { useState } from "react";
import {
	Message,
	MessageAction,
	MessageActions,
	MessageContent,
	MessageResponse,
	MessageToolbar,
} from "@/components/ai-elements/message";
import {
	Reasoning,
	ReasoningContent,
	ReasoningTrigger,
} from "@/components/ai-elements/reasoning";
import {
	Tool,
	ToolContent,
	ToolHeader,
	ToolInput,
	ToolOutput,
} from "@/components/ai-elements/tool";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { ChatMessage, ToolInvocation } from "../types";

type ChatMessageItemProps = {
	message: ChatMessage;
	canRegenerate?: boolean;
	onEditUserMessage: (messageId: string, content: string) => Promise<void>;
	onRegenerate: () => Promise<void>;
};

type Feedback = "liked" | "disliked";

const toToolState = (status: ToolInvocation["status"]) => {
	if (status === "running") {
		return "input-available" as const;
	}

	if (status === "error") {
		return "output-error" as const;
	}

	return "output-available" as const;
};

function ToolInvocationDetails({ invocation }: { invocation: ToolInvocation }) {
	return (
		<Tool className="mb-0 border-zinc-200 bg-zinc-50/70" defaultOpen={false}>
			<ToolHeader
				state={toToolState(invocation.status)}
				toolName={invocation.toolName}
				type="dynamic-tool"
			/>
			<ToolContent>
				<ToolInput input={invocation.args} />
				{typeof invocation.latencyMs === "number" && (
					<p className="text-muted-foreground text-xs">
						Latency: {invocation.latencyMs}ms
					</p>
				)}
				<ToolOutput errorText={invocation.error} output={invocation.result} />
			</ToolContent>
		</Tool>
	);
}

export function ChatMessageItem({
	message,
	canRegenerate = false,
	onEditUserMessage,
	onRegenerate,
}: ChatMessageItemProps) {
	const [copied, setCopied] = useState(false);
	const [feedback, setFeedback] = useState<Feedback>();
	const [isEditing, setIsEditing] = useState(false);
	const [draft, setDraft] = useState(message.content);
	const [isSaving, setIsSaving] = useState(false);
	const isUser = message.role === "user";
	const isStreaming = message.status === "streaming";

	const copyMessage = async () => {
		await navigator.clipboard.writeText(message.content);
		setCopied(true);
		window.setTimeout(() => setCopied(false), 1200);
	};

	const saveEdit = async () => {
		const nextContent = draft.trim();

		if (!nextContent || nextContent === message.content) {
			setIsEditing(false);
			setDraft(message.content);
			return;
		}

		setIsSaving(true);

		try {
			await onEditUserMessage(message.id, nextContent);
			setIsEditing(false);
		} finally {
			setIsSaving(false);
		}
	};

	return (
		<Message
			className={cn("max-w-full", isUser ? "items-end" : "items-start")}
			from={isUser ? "user" : "assistant"}
		>
			<MessageContent
				className={cn(
					isUser
						? "max-w-[75%] rounded-3xl bg-zinc-100 px-4 py-3 text-zinc-900"
						: "w-full max-w-none text-zinc-900",
				)}
			>
				{isEditing ? (
					<div className="w-[min(42rem,75vw)] space-y-3">
						<Textarea
							className="min-h-24 resize-none border-zinc-200 bg-white text-sm"
							onChange={(event) => setDraft(event.target.value)}
							value={draft}
						/>
						<div className="flex justify-end gap-2">
							<Button
								disabled={isSaving}
								onClick={() => {
									setIsEditing(false);
									setDraft(message.content);
								}}
								size="sm"
								type="button"
								variant="ghost"
							>
								Cancel
							</Button>
							<Button
								disabled={isSaving || !draft.trim()}
								onClick={saveEdit}
								size="sm"
								type="button"
							>
								Save
							</Button>
						</div>
					</div>
				) : (
					<>
						{message.reasoning && (
							<Reasoning isStreaming={isStreaming}>
								<ReasoningTrigger />
								<ReasoningContent>{message.reasoning}</ReasoningContent>
							</Reasoning>
						)}
						{message.content ? (
							isUser ? (
								<p className="whitespace-pre-wrap">{message.content}</p>
							) : (
								<MessageResponse isAnimating={isStreaming}>
									{message.content}
								</MessageResponse>
							)
						) : (
							<p className="text-muted-foreground text-sm">
								{isStreaming ? "Thinking..." : "No content"}
							</p>
						)}
						{message.toolInvocations?.map((invocation) => (
							<ToolInvocationDetails
								invocation={invocation}
								key={invocation.id}
							/>
						))}
					</>
				)}
			</MessageContent>

			{!isEditing && (
				<MessageToolbar
					className={cn(
						"mt-1 justify-start opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100",
						isUser && "justify-end",
					)}
				>
					<MessageActions>
						<MessageAction
							label={copied ? "Copied" : "Copy"}
							onClick={copyMessage}
							tooltip={copied ? "Copied" : "Copy"}
						>
							{copied ? (
								<CheckIcon className="size-4" />
							) : (
								<CopyIcon className="size-4" />
							)}
						</MessageAction>
						{isUser ? (
							<MessageAction
								label="Edit"
								onClick={() => setIsEditing(true)}
								tooltip="Edit"
							>
								<PencilIcon className="size-4" />
							</MessageAction>
						) : (
							<>
								{canRegenerate && (
									<MessageAction
										label="Regenerate"
										onClick={() => void onRegenerate()}
										tooltip="Regenerate"
									>
										<RotateCcwIcon className="size-4" />
									</MessageAction>
								)}
								<MessageAction
									className={cn(feedback === "liked" && "bg-zinc-100")}
									label="Like"
									onClick={() =>
										setFeedback(feedback === "liked" ? undefined : "liked")
									}
									tooltip="Like"
								>
									<ThumbsUpIcon className="size-4" />
								</MessageAction>
								<MessageAction
									className={cn(feedback === "disliked" && "bg-zinc-100")}
									label="Dislike"
									onClick={() =>
										setFeedback(
											feedback === "disliked" ? undefined : "disliked",
										)
									}
									tooltip="Dislike"
								>
									<ThumbsDownIcon className="size-4" />
								</MessageAction>
							</>
						)}
					</MessageActions>
					{message.status === "error" && (
						<div className="flex items-center gap-1 text-red-600 text-xs">
							<XIcon className="size-3" />
							Message failed
						</div>
					)}
				</MessageToolbar>
			)}
		</Message>
	);
}
