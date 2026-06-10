"use client";

import { SendHorizontalIcon, SquareIcon, TerminalIcon } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
	getPendingApprovalForInput,
	isConversationInputLocked,
} from "../chat-ui-state";
import {
	getNextSlashCommandIndex,
	getSlashCommandSuggestions,
	isExactSlashCommand,
} from "../slash-commands";
import { useChatStore } from "../store";
import { ApprovalCard } from "./approval-card";

export function ChatInput() {
	const [draft, setDraft] = useState("");
	const [selectedSlashCommandIndex, setSelectedSlashCommandIndex] = useState(0);
	const textareaRef = useRef<HTMLTextAreaElement>(null);
	const slashCommandListboxId = useId();
	const isLocked = useChatStore((state) =>
		isConversationInputLocked(state, state.activeConversationId),
	);
	const pendingApproval = useChatStore(getPendingApprovalForInput);
	const activeConversationId = useChatStore(
		(state) => state.activeConversationId,
	);
	const sendMessage = useChatStore((state) => state.sendMessage);
	const stopStreaming = useChatStore((state) => state.stopStreaming);
	const pathname = usePathname();
	const router = useRouter();

	const trimmedDraft = draft.trim();
	const slashCommandSuggestions = isLocked
		? []
		: getSlashCommandSuggestions(draft);
	const hasIncompleteSlashCommand =
		slashCommandSuggestions.length > 0 && !isExactSlashCommand(draft);
	const canSend =
		trimmedDraft.length > 0 && !isLocked && !hasIncompleteSlashCommand;
	const selectedSlashCommandOptionIndex = slashCommandSuggestions[
		selectedSlashCommandIndex
	]
		? selectedSlashCommandIndex
		: 0;
	const selectedSlashCommand =
		slashCommandSuggestions[selectedSlashCommandOptionIndex] ??
		slashCommandSuggestions[0];

	useEffect(() => {
		setSelectedSlashCommandIndex(0);
	}, [draft]);

	const selectSlashCommand = (commandValue: string) => {
		setDraft(commandValue);
		requestAnimationFrame(() => {
			textareaRef.current?.focus();
			textareaRef.current?.setSelectionRange(
				commandValue.length,
				commandValue.length,
			);
		});
	};

	const submitMessage = () => {
		if (hasIncompleteSlashCommand) {
			if (selectedSlashCommand) {
				selectSlashCommand(selectedSlashCommand.value);
			}
			return;
		}

		if (!canSend) {
			return;
		}

		const nextMessage = trimmedDraft;
		setDraft("");
		void sendMessage(nextMessage).then((conversationId) => {
			if (pathname === "/chat" && conversationId) {
				router.replace(`/chat/${encodeURIComponent(conversationId)}`);
			}
		});
	};

	const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
		if (
			slashCommandSuggestions.length > 0 &&
			(event.key === "ArrowDown" || event.key === "ArrowUp")
		) {
			event.preventDefault();
			setSelectedSlashCommandIndex((currentIndex) =>
				getNextSlashCommandIndex({
					currentIndex,
					direction: event.key === "ArrowDown" ? "next" : "previous",
					itemCount: slashCommandSuggestions.length,
				}),
			);
			return;
		}

		if (
			event.key !== "Enter" ||
			event.shiftKey ||
			event.nativeEvent.isComposing
		) {
			return;
		}

		event.preventDefault();
		if (hasIncompleteSlashCommand) {
			if (selectedSlashCommand) {
				selectSlashCommand(selectedSlashCommand.value);
			}
			return;
		}

		submitMessage();
	};

	return (
		<footer className="shrink-0 bg-white px-6 pt-4 pb-5">
			<div className="relative mx-auto w-full max-w-6xl">
				{pendingApproval && activeConversationId ? (
					<div className="absolute right-0 bottom-full left-0 z-30 mb-3">
						<ApprovalCard
							batch={pendingApproval}
							conversationId={activeConversationId}
							variant="floating"
						/>
					</div>
				) : null}
				<form
					className="relative rounded-3xl border border-zinc-200 bg-white shadow-[0_14px_44px_rgba(15,23,42,0.10)]"
					onSubmit={(event) => {
						event.preventDefault();
						submitMessage();
					}}
				>
					{slashCommandSuggestions.length > 0 ? (
						<div
							id={slashCommandListboxId}
							className="absolute right-0 bottom-full left-0 z-20 mb-2 overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-[0_18px_50px_rgba(15,23,42,0.14)]"
							role="listbox"
						>
							{slashCommandSuggestions.map((command, index) => (
								<button
									aria-selected={index === selectedSlashCommandOptionIndex}
									className={cn(
										"flex w-full items-center gap-3 px-4 py-3 text-left text-sm focus-visible:outline-none",
										index === selectedSlashCommandOptionIndex
											? "bg-zinc-100"
											: "hover:bg-zinc-50 focus-visible:bg-zinc-50",
									)}
									id={`${slashCommandListboxId}-${index}`}
									key={command.value}
									onClick={() => selectSlashCommand(command.value)}
									onMouseEnter={() => setSelectedSlashCommandIndex(index)}
									onMouseDown={(event) => event.preventDefault()}
									role="option"
									type="button"
								>
									<span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-zinc-900 text-white">
										<TerminalIcon className="size-4" />
									</span>
									<span className="min-w-0 flex-1">
										<span className="block font-medium text-zinc-950">
											{command.label}
										</span>
										<span className="block truncate text-[12px] text-zinc-500">
											<span className="font-mono">{command.value}</span>
											{" · "}
											{command.description}
										</span>
									</span>
									<span className="rounded-md border border-zinc-200 px-2 py-1 font-mono text-[11px] text-zinc-500">
										Enter
									</span>
								</button>
							))}
						</div>
					) : null}
					<div className="flex items-end gap-2">
						<Textarea
							aria-activedescendant={
								slashCommandSuggestions.length > 0
									? `${slashCommandListboxId}-${selectedSlashCommandOptionIndex}`
									: undefined
							}
							aria-label="Message"
							aria-controls={
								slashCommandSuggestions.length > 0
									? slashCommandListboxId
									: undefined
							}
							aria-expanded={slashCommandSuggestions.length > 0}
							className="max-h-52 min-h-12 resize-none border-0 bg-transparent px-3 py-3 text-[15px] text-zinc-900 shadow-none placeholder:text-zinc-400 focus-visible:ring-0"
							disabled={isLocked}
							onChange={(event) => setDraft(event.target.value)}
							onKeyDown={handleKeyDown}
							placeholder="Ask anything"
							ref={textareaRef}
							rows={1}
							value={draft}
						/>
						{isLocked ? (
							<Button
								aria-label="Stop response"
								className="mb-1 size-9 rounded-full bg-zinc-900 text-white hover:bg-zinc-700"
								onClick={stopStreaming}
								size="icon"
								type="button"
							>
								<SquareIcon className="size-3.5 fill-current" />
							</Button>
						) : (
							<Button
								aria-label="Send message"
								className="mb-1 size-9 rounded-full bg-zinc-900 text-white hover:bg-zinc-700 disabled:bg-zinc-200 disabled:text-zinc-400"
								disabled={!canSend}
								size="icon"
								type="submit"
							>
								<SendHorizontalIcon className="size-4" />
							</Button>
						)}
					</div>
				</form>
				<p className="mt-2 text-center text-[12px] text-zinc-500">
					AI can make mistakes. Check important info.
				</p>
			</div>
		</footer>
	);
}
