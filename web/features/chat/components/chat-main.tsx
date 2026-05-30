"use client";

import { XIcon } from "lucide-react";
import { useChatStore } from "../store";
import { ChatInput } from "./chat-input";
import { ChatMessageList } from "./chat-message-list";

export function ChatMain() {
	const error = useChatStore((state) => state.error);
	const clearError = useChatStore((state) => state.clearError);

	return (
		<main className="flex min-w-0 flex-1 flex-col bg-white">
			<header className="flex h-14 shrink-0 items-center border-zinc-200 border-b px-6">
				<h1 className="font-semibold text-base text-zinc-900">
					AI Chat Assistant
				</h1>
			</header>
			{error && (
				<div className="border-red-200 border-b bg-red-50 px-6 py-3">
					<div className="mx-auto flex max-w-3xl items-start justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-red-800">
						<p className="text-sm leading-5">{error.message}</p>
						<button
							aria-label="Dismiss error"
							className="rounded-md p-1 text-red-600 transition-colors hover:bg-red-100 hover:text-red-800"
							onClick={clearError}
							type="button"
						>
							<XIcon className="size-4" />
						</button>
					</div>
				</div>
			)}
			<section className="flex min-h-0 flex-1 flex-col">
				<ChatMessageList />
				<ChatInput />
			</section>
		</main>
	);
}
