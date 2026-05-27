"use client";

import {
  Bot,
  MessageSquare,
  Sparkles,
  User,
} from "lucide-react";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  Message,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { useChatStream } from "./useChatStream";

const pageContext = {
  route: "/",
  symbol: "AAPL",
  eventId: "",
  researchCardId: "",
};

function getAssistantFallback(status: string) {
  if (status === "pending") {
    return "正在连接 Agent...";
  }

  if (status === "aborted") {
    return "已停止生成，你可以继续追问。";
  }

  return "";
}

export function ChatPanel() {
  const {
    composerInput,
    error,
    isStreaming,
    messages,
    sendMessage,
    setComposerInput,
    stop,
  } = useChatStream();

  const onSubmit = async (message: PromptInputMessage) => {
    if (!message.text.trim()) {
      return;
    }

    try {
      await sendMessage(pageContext, message.text);
    } catch {
      return;
    }
  };

  return (
    <section className="flex min-h-[640px] flex-col overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-sm">
      <div className="border-b border-zinc-200 bg-linear-to-r from-emerald-50 via-white to-cyan-50 px-5 py-4">
        <div>
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-zinc-950">
              <Sparkles className="size-4 text-emerald-600" />
              AI 对话
            </div>
            <p className="mt-1 text-xs leading-5 text-zinc-500">
              AAPL / 首页上下文
            </p>
          </div>
        </div>
      </div>

      <Conversation className="bg-zinc-50/70">
        <ConversationContent>
          {messages.length === 0 ? (
            <ConversationEmptyState
              icon={<MessageSquare className="size-5" aria-hidden="true" />}
              title="建议的提问方向"
            >
              <div className="grid gap-2">
                {[
                  "结合最新财报，分析 AAPL 未来两个季度的风险点",
                  "对比 NVDA 和 MSFT 的估值弹性与盈利确定性",
                  "如果出现宏观回撤，当前自选股里谁更抗跌？",
                ].map((prompt) => (
                  <button
                    className="rounded-md border border-zinc-200 bg-zinc-50 px-3 py-3 text-left text-sm leading-6 text-zinc-600 hover:border-emerald-200 hover:bg-emerald-50 hover:text-emerald-800"
                    key={prompt}
                    onClick={() => setComposerInput(prompt)}
                    type="button"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </ConversationEmptyState>
          ) : (
            messages.map((message) => (
              <Message from={message.role} key={message.id}>
                <MessageContent
                  className={
                    message.role === "user"
                      ? "bg-emerald-700 px-4 py-3 text-white"
                      : "rounded-lg border border-zinc-200 bg-white px-4 py-3 shadow-xs"
                  }
                >
                  <div className="mb-2 flex items-center gap-2 text-[11px] font-medium uppercase opacity-70">
                    {message.role === "user" ? (
                      <User className="size-3.5" aria-hidden="true" />
                    ) : (
                      <Bot className="size-3.5" aria-hidden="true" />
                    )}
                    {message.role === "user" ? "You" : "Agent"}
                  </div>
                  {message.role === "assistant" ? (
                    <MessageResponse>
                      {message.content || getAssistantFallback(message.status)}
                    </MessageResponse>
                  ) : (
                    <div className="whitespace-pre-wrap">{message.content}</div>
                  )}
                </MessageContent>
              </Message>
            ))
          )}

          {error ? (
            <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {error}
            </p>
          ) : null}
        </ConversationContent>
        {messages.length > 0 ? <ConversationScrollButton /> : null}
      </Conversation>

      <div className="border-t border-zinc-200 bg-zinc-50/70 p-4 md:p-5">
        <PromptInput onSubmit={onSubmit}>
          <PromptInputBody>
            <PromptInputTextarea
              onChange={(event) => setComposerInput(event.target.value)}
              placeholder="输入你想追问的股票或事件"
              value={composerInput}
            />
          </PromptInputBody>
          <PromptInputFooter>
            <div className="min-w-0 text-xs text-zinc-500">
              {isStreaming ? "正在接收回答" : "⌘ Enter 发送"}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <PromptInputSubmit
                aria-label={isStreaming ? "停止回答" : "发送"}
                onStop={stop}
                status={isStreaming ? "streaming" : "ready"}
              />
            </div>
          </PromptInputFooter>
        </PromptInput>
      </div>
    </section>
  );
}
