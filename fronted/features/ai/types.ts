export type MessageStatus =
  | "pending"
  | "streaming"
  | "completed"
  | "error"
  | "aborted";

export type ChatRole = "user" | "assistant";

export type PageContext = {
  route: string;
  symbol: string;
  eventId: string;
  researchCardId: string;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  status: MessageStatus;
};

export type ChatStreamRequest = {
  conversationId: string;
  content: string;
  pageContext: PageContext;
};

export type ChatStreamEvent =
  | {
      type: "metadata";
      conversationId: string;
      userMessageId: string;
      assistantMessageId: string;
    }
  | { type: "delta"; content: string }
  | { type: "done"; finishReason: string }
  | { type: "error"; code: string; message: string };
