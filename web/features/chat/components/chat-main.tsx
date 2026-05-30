import { ChatMessageList } from "./chat-message-list";

export function ChatMain() {
	return (
		<main className="flex min-w-0 flex-1 flex-col bg-white">
			<header className="flex h-14 shrink-0 items-center border-zinc-200 border-b px-6">
				<h1 className="font-semibold text-base text-zinc-900">
					AI Chat Assistant
				</h1>
			</header>
			<section className="flex min-h-0 flex-1 flex-col">
				<ChatMessageList />
			</section>
		</main>
	);
}
