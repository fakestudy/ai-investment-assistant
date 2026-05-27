import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "AI 投资助手",
  description: "个人美股研究工作台",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full bg-zinc-50 font-sans antialiased">
      <body className="min-h-full bg-zinc-50 text-zinc-950">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
