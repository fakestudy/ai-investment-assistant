"use client";

import { useEffect } from "react";
import { toast } from "sonner";
import { useChatStore } from "../store";

export function ChatErrorToast() {
	const error = useChatStore((state) => state.error);
	const clearError = useChatStore((state) => state.clearError);

	useEffect(() => {
		if (!error) {
			return;
		}

		toast.error(error.message, {
			id: `${error.scope}:${error.message}`,
		});
		clearError();
	}, [clearError, error]);

	return null;
}
