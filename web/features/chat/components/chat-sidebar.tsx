"use client";

import {
	MessageSquareIcon,
	PencilIcon,
	PlusIcon,
	Trash2Icon,
} from "lucide-react";
import { useState } from "react";
import { useChatStore } from "../store";
import type { Conversation } from "../types";
import { DeleteConversationDialog } from "./delete-conversation-dialog";
import { RenameConversationDialog } from "./rename-conversation-dialog";

type ConversationRowProps = {
	conversation: Conversation;
	isActive: boolean;
	onDelete: () => void;
	onRename: () => void;
	onSelect: () => void;
};

function ConversationRow({
	conversation,
	isActive,
	onDelete,
	onRename,
	onSelect,
}: ConversationRowProps) {
	return (
		<div
			className={[
				"group flex items-center gap-1 rounded-lg px-2 py-1.5 transition-colors",
				isActive
					? "bg-white shadow-sm ring-1 ring-zinc-200"
					: "hover:bg-zinc-100",
			].join(" ")}
		>
			<button
				className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm text-zinc-800"
				onClick={onSelect}
				type="button"
			>
				<MessageSquareIcon className="size-4 shrink-0 text-zinc-500" />
				<span className="truncate">
					{conversation.title || "Untitled chat"}
				</span>
			</button>
			{isActive && (
				<div className="flex shrink-0 items-center gap-0.5">
					<button
						aria-label="Rename conversation"
						className="rounded-md p-1 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
						onClick={onRename}
						type="button"
					>
						<PencilIcon className="size-3.5" />
					</button>
					<button
						aria-label="Delete conversation"
						className="rounded-md p-1 text-zinc-500 transition-colors hover:bg-red-50 hover:text-red-600"
						onClick={onDelete}
						type="button"
					>
						<Trash2Icon className="size-3.5" />
					</button>
				</div>
			)}
		</div>
	);
}

export function ChatSidebar() {
	const conversations = useChatStore((state) => state.conversations);
	const activeConversationId = useChatStore(
		(state) => state.activeConversationId,
	);
	const createNewConversation = useChatStore(
		(state) => state.createNewConversation,
	);
	const selectConversation = useChatStore((state) => state.selectConversation);
	const isLoadingConversations = useChatStore(
		(state) => state.isLoadingConversations,
	);
	const renameActiveConversation = useChatStore(
		(state) => state.renameActiveConversation,
	);
	const deleteActiveConversation = useChatStore(
		(state) => state.deleteActiveConversation,
	);
	const activeConversation = conversations.find(
		(conversation) => conversation.id === activeConversationId,
	);
	const [isRenameDialogOpen, setIsRenameDialogOpen] = useState(false);
	const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);

	return (
		<aside className="flex w-[260px] shrink-0 flex-col border-zinc-200 border-r bg-zinc-50 p-3">
			<button
				className="flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 font-medium text-sm text-zinc-900 shadow-sm transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-60"
				disabled={isLoadingConversations}
				onClick={() => {
					void createNewConversation();
				}}
				type="button"
			>
				<PlusIcon className="size-4" />
				New chat
			</button>
			<nav className="mt-4 flex flex-1 flex-col gap-1 overflow-y-auto">
				{conversations.map((conversation) => (
					<ConversationRow
						conversation={conversation}
						isActive={conversation.id === activeConversationId}
						key={conversation.id}
						onDelete={() => {
							setIsDeleteDialogOpen(true);
						}}
						onRename={() => {
							setIsRenameDialogOpen(true);
						}}
						onSelect={() => {
							void selectConversation(conversation.id);
						}}
					/>
				))}
			</nav>
			<RenameConversationDialog
				conversation={activeConversation}
				open={isRenameDialogOpen}
				onOpenChange={setIsRenameDialogOpen}
				onRename={(title) => renameActiveConversation(title)}
			/>
			<DeleteConversationDialog
				conversation={activeConversation}
				open={isDeleteDialogOpen}
				onOpenChange={setIsDeleteDialogOpen}
				onDelete={deleteActiveConversation}
			/>
		</aside>
	);
}
