"use client";

import { useChatStore } from "./chat-store";

export function useChatStream() {
  return useChatStore((state) => state);
}
