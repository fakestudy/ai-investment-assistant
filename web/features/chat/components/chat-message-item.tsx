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
import { memo, useState } from "react";
import {
	Message,
	MessageAction,
	MessageActions,
	MessageContent,
	MessageToolbar,
} from "@/components/ai-elements/message";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "../types";
import { ChatMarkdown } from "./chat-markdown";
import {
	ChatMessageTimeline,
	hasTimelineDetails,
} from "./chat-message-timeline";

type ChatMessageItemProps = {
	message: ChatMessage;
	canRegenerate?: boolean;
	onEditUserMessage: (
		messageId: string,
		previousContent: string,
		nextContent: string,
	) => Promise<void>;
	onRegenerate: () => Promise<void>;
};

type Feedback = "liked" | "disliked";

function ChatMessageItemComponent({
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
		setIsEditing(false);

		try {
			await onEditUserMessage(message.id, message.content, nextContent);
		} finally {
			setIsSaving(false);
		}
	};

	return (
		<Message
			className={cn("max-w-full", isUser ? "items-end" : "items-start")}
			from={isUser ? "user" : "assistant"}
		>
			{isEditing ? (
				<div className="w-full max-w-[min(63rem,75vw)] space-y-3 rounded-2xl border border-zinc-200 bg-white p-3 shadow-sm">
					<Textarea
						className="min-h-24 resize-none rounded-2xl border-zinc-200 bg-white text-sm"
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
				<MessageContent
					className={cn(
						isUser
							? "max-w-[75%] rounded-3xl bg-zinc-100 px-4 py-3 text-zinc-900 shadow-sm"
							: "w-full max-w-none text-zinc-900",
					)}
				>
					<ChatMessageTimeline isStreaming={isStreaming} message={message} />
					{message.content ? (
						isUser ? (
							<p className="whitespace-pre-wrap">{message.content}</p>
						) : (
							<ChatMarkdown content={message.content} />
						)
					) : !hasTimelineDetails(message) ? (
						<p className="text-muted-foreground text-sm">
							{isStreaming ? "Thinking..." : "No content"}
						</p>
					) : null}
				</MessageContent>
			)}

			{!isEditing && (
				<MessageToolbar
					className={cn(
						"mt-1 justify-start text-zinc-500 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100",
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
								onClick={() => {
									setDraft(message.content);
									setIsEditing(true);
								}}
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

export const ChatMessageItem = memo(
	ChatMessageItemComponent,
	(previousProps, nextProps) =>
		previousProps.message === nextProps.message &&
		previousProps.canRegenerate === nextProps.canRegenerate &&
		previousProps.onEditUserMessage === nextProps.onEditUserMessage &&
		previousProps.onRegenerate === nextProps.onRegenerate,
);

ChatMessageItem.displayName = "ChatMessageItem";
