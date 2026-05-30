"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { Conversation } from "../types";

type RenameConversationDialogProps = {
	conversation?: Conversation;
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onRename: (title: string) => Promise<void>;
};

export function RenameConversationDialog({
	conversation,
	open,
	onOpenChange,
	onRename,
}: RenameConversationDialogProps) {
	const [title, setTitle] = useState(conversation?.title ?? "");
	const [isSubmitting, setIsSubmitting] = useState(false);

	useEffect(() => {
		if (open) {
			setTitle(conversation?.title ?? "");
		}
	}, [conversation?.title, open]);

	const trimmedTitle = title.trim();
	const isSubmitDisabled =
		isSubmitting ||
		!conversation ||
		!trimmedTitle ||
		trimmedTitle === conversation.title;

	return (
		<Dialog onOpenChange={onOpenChange} open={open}>
			<DialogContent>
				<form
					className="grid gap-4"
					onSubmit={(event) => {
						event.preventDefault();

						if (isSubmitDisabled) {
							return;
						}

						setIsSubmitting(true);
						void onRename(trimmedTitle).finally(() => {
							setIsSubmitting(false);
							onOpenChange(false);
						});
					}}
				>
					<DialogHeader>
						<DialogTitle>Rename conversation</DialogTitle>
						<DialogDescription>
							Update the name shown in the conversation sidebar.
						</DialogDescription>
					</DialogHeader>
					<Input
						autoFocus
						onChange={(event) => setTitle(event.target.value)}
						placeholder="Conversation name"
						value={title}
					/>
					<DialogFooter>
						<Button
							disabled={isSubmitting}
							onClick={() => onOpenChange(false)}
							type="button"
							variant="outline"
						>
							Cancel
						</Button>
						<Button disabled={isSubmitDisabled} type="submit">
							Save
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
