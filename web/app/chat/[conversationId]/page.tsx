import { ChatShell } from "@/features/chat/components/chat-shell";

type ChatConversationPageProps = {
	params: Promise<{
		conversationId: string;
	}>;
};

export default async function ChatConversationPage({
	params,
}: ChatConversationPageProps) {
	const { conversationId } = await params;

	return <ChatShell conversationId={conversationId} />;
}
