"use client";

import { Send, Square } from "lucide-react";
import { useState } from "react";
import { useChatStream } from "./useChatStream";

export function ChatPanel() {
  const [input, setInput] = useState("");
  const { messages, sendMessage, stop } = useChatStream();
  const [error, setError] = useState("");

  const onSubmit = async () => {
    setError("");
    try {
      await sendMessage(input, {
        route: "/",
        symbol: "AAPL",
        eventId: "",
        researchCardId: "",
      });
      setInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败");
    }
  };

  return (
    <section className="flex min-h-[560px] flex-col rounded-lg border border-zinc-200 bg-white">
      <div className="border-b border-zinc-200 px-4 py-3">
        <div className="text-sm font-medium text-zinc-900">AI 对话</div>
      </div>
      <div className="flex flex-1 flex-col gap-3 p-4">
        {messages.length === 0 ? (
          <div className="max-w-[85%] rounded-lg bg-zinc-100 px-3 py-2 text-sm leading-6 text-zinc-700">
            今天可以先从自选股风险、财报变化或宏观事件切入。
          </div>
        ) : (
          messages.map((message) => (
            <div
              className={
                message.role === "user"
                  ? "ml-auto max-w-[85%] rounded-lg bg-emerald-700 px-3 py-2 text-sm leading-6 text-white"
                  : "max-w-[85%] rounded-lg bg-zinc-100 px-3 py-2 text-sm leading-6 text-zinc-700"
              }
              key={message.id}
            >
              {message.content ||
                (message.status === "pending" ? "正在连接 Agent..." : "")}
            </div>
          ))
        )}
        {error ? <p className="text-sm text-rose-700">{error}</p> : null}
        <div className="mt-auto rounded-lg border border-zinc-200 bg-zinc-50 p-2">
          <textarea
            className="min-h-24 w-full resize-none bg-transparent p-2 text-sm outline-none placeholder:text-zinc-400"
            onChange={(event) => setInput(event.target.value)}
            placeholder="输入你想追问的股票或事件"
            value={input}
          />
          <div className="flex items-center justify-between border-t border-zinc-200 px-2 pt-2">
            <button
              aria-label="停止回答"
              className="inline-flex size-8 items-center justify-center rounded-md text-zinc-500 hover:bg-zinc-100"
              onClick={stop}
              type="button"
            >
              <Square className="size-4" aria-hidden="true" />
            </button>
            <button
              className="inline-flex items-center gap-2 rounded-md bg-emerald-700 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-800"
              onClick={onSubmit}
              type="button"
            >
              <Send className="size-4" aria-hidden="true" />
              发送
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
