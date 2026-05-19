import {
  Bell,
  BrainCircuit,
  LineChart,
  Search,
  ShieldCheck,
  Star,
  TrendingUp,
} from "lucide-react";
import { ChatPanel } from "@/features/ai/ChatPanel";

export default function Home() {
  return (
    <main className="min-h-screen bg-zinc-50">
      <header className="border-b border-zinc-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-md border border-emerald-200 bg-emerald-50 text-emerald-700">
              <BrainCircuit className="size-5" aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-base font-semibold text-zinc-950">
                AI 投资助手
              </h1>
              <p className="text-xs text-zinc-500">非投资建议，仅供研究参考</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              className="inline-flex size-9 items-center justify-center rounded-md border border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-50"
              type="button"
              aria-label="搜索"
            >
              <Search className="size-4" aria-hidden="true" />
            </button>
            <button
              className="inline-flex size-9 items-center justify-center rounded-md border border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-50"
              type="button"
              aria-label="消息"
            >
              <Bell className="size-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-4 px-4 py-4 sm:px-6 lg:grid-cols-[minmax(280px,360px)_minmax(0,1fr)_minmax(240px,300px)] lg:px-8">
        <ChatPanel />

        <section className="min-h-[560px] rounded-lg border border-zinc-200 bg-white">
          <div className="border-b border-zinc-200 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-medium text-zinc-900">
              <LineChart className="size-4 text-blue-700" />
              研究工作台
            </div>
          </div>
          <div className="grid gap-4 p-4 md:grid-cols-3">
            {[
              ["AAPL", "+1.24%", "收入增速和硬件周期"],
              ["NVDA", "-0.42%", "估值、供给和监管"],
              ["MSFT", "+0.68%", "云业务和 AI 投入"],
            ].map(([symbol, change, note]) => (
              <article
                className="rounded-lg border border-zinc-200 p-4"
                key={symbol}
              >
                <div className="flex items-center justify-between">
                  <div className="font-mono text-sm font-semibold text-zinc-950">
                    {symbol}
                  </div>
                  <div
                    className={
                      change.startsWith("+")
                        ? "text-sm font-medium text-emerald-700"
                        : "text-sm font-medium text-rose-700"
                    }
                  >
                    {change}
                  </div>
                </div>
                <p className="mt-3 text-sm leading-6 text-zinc-600">{note}</p>
              </article>
            ))}
          </div>
          <div className="mx-4 rounded-lg border border-dashed border-zinc-300 bg-zinc-50 p-6">
            <div className="flex items-center gap-2 text-sm font-medium text-zinc-800">
              <ShieldCheck className="size-4 text-amber-600" />
              当前上下文
            </div>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-600">
              页面上下文会在后续对话流中作为 `pageContext` 传给 BFF，再由
              gRPC streaming 转交给 Agent。
            </p>
          </div>
        </section>

        <aside className="rounded-lg border border-zinc-200 bg-white">
          <div className="border-b border-zinc-200 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-medium text-zinc-900">
              <Star className="size-4 text-amber-600" />
              自选股
            </div>
          </div>
          <div className="space-y-3 p-4">
            {["AAPL", "NVDA", "MSFT", "TSLA"].map((symbol) => (
              <button
                className="flex w-full items-center justify-between rounded-md border border-zinc-200 px-3 py-2 text-left hover:bg-zinc-50"
                key={symbol}
                type="button"
              >
                <span className="font-mono text-sm font-medium text-zinc-900">
                  {symbol}
                </span>
                <TrendingUp className="size-4 text-emerald-700" />
              </button>
            ))}
          </div>
        </aside>
      </div>
    </main>
  );
}
