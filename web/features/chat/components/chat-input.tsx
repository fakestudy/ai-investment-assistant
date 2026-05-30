"use client";

import { SendHorizontalIcon, SquareIcon } from "lucide-react";
import { type KeyboardEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useChatStore } from "../store";

export function ChatInput() {
	const [draft, setDraft] = useState("");
	const isStreaming = useChatStore((state) => state.isStreaming);
	const sendMessage = useChatStore((state) => state.sendMessage);
	const stopStreaming = useChatStore((state) => state.stopStreaming);

	const trimmedDraft = draft.trim();
	const canSend = trimmedDraft.length > 0 && !isStreaming;

	const submitMessage = () => {
		if (!canSend) {
			return;
		}

		const nextMessage = trimmedDraft;
		setDraft("");
		void sendMessage(nextMessage);
	};

	const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
		if (
			event.key !== "Enter" ||
			event.shiftKey ||
			event.nativeEvent.isComposing
		) {
			return;
		}

		event.preventDefault();
		submitMessage();
	};

	return (
		<footer className="shrink-0 border-zinc-100 border-t bg-white px-6 pt-4 pb-5">
			<div className="mx-auto w-full max-w-3xl">
				<form
					className="rounded-3xl border border-zinc-200 bg-white p-2 shadow-[0_8px_28px_rgba(15,23,42,0.08)]"
					onSubmit={(event) => {
						event.preventDefault();
						submitMessage();
					}}
				>
					<div className="flex items-end gap-2">
						<Textarea
							aria-label="Message"
							className="max-h-52 min-h-12 resize-none border-0 bg-transparent px-3 py-3 text-[15px] shadow-none focus-visible:ring-0"
							disabled={isStreaming}
							onChange={(event) => setDraft(event.target.value)}
							onKeyDown={handleKeyDown}
							placeholder="Ask anything"
							rows={1}
							value={draft}
						/>
						{isStreaming ? (
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
