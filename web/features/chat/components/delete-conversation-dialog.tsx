"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import type { Conversation } from "../types";

type DeleteConversationDialogProps = {
	conversation?: Conversation;
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onDelete: () => Promise<void>;
};

export function DeleteConversationDialog({
	conversation,
	open,
	onOpenChange,
	onDelete,
}: DeleteConversationDialogProps) {
	const [isDeleting, setIsDeleting] = useState(false);

	return (
		<Dialog onOpenChange={onOpenChange} open={open}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>Delete conversation?</DialogTitle>
					<DialogDescription>
						This removes "{conversation?.title || "Untitled chat"}" from the
						sidebar. This action cannot be undone.
					</DialogDescription>
				</DialogHeader>
				<DialogFooter>
					<Button
						disabled={isDeleting}
						onClick={() => onOpenChange(false)}
						type="button"
						variant="outline"
					>
						Cancel
					</Button>
					<Button
						disabled={isDeleting || !conversation}
						onClick={() => {
							setIsDeleting(true);
							void onDelete().finally(() => {
								setIsDeleting(false);
								onOpenChange(false);
							});
						}}
						type="button"
						variant="destructive"
					>
						Delete
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
