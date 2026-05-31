"use client";

import type { ComponentProps } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { BundledLanguage } from "shiki";
import {
	CodeBlock,
	CodeBlockActions,
	CodeBlockCopyButton,
	CodeBlockFilename,
	CodeBlockHeader,
	CodeBlockTitle,
} from "@/components/ai-elements/code-block";

type ChatMarkdownProps = {
	content: string;
};

export const normalizeMarkdownCodeLanguage = (className?: string) => {
	const language = className?.match(/language-(\S+)/)?.[1]?.trim();

	return language || "text";
};

const getCodeText = (children: ComponentProps<"code">["children"]) =>
	String(children).replace(/\n$/, "");

export function ChatMarkdown({ content }: ChatMarkdownProps) {
	return (
		<div className="chat-markdown">
			<ReactMarkdown
				components={{
					code({ children, className, ...props }) {
						const rawCode = String(children);
						const code = getCodeText(children);
						const language = normalizeMarkdownCodeLanguage(className);
						const isCodeBlock = Boolean(className) || rawCode.includes("\n");

						if (!isCodeBlock) {
							return (
								<code className="chat-markdown-inline-code" {...props}>
									{children}
								</code>
							);
						}

						return (
							<CodeBlock
								code={code}
								language={language as BundledLanguage}
								showLineNumbers={code.split("\n").length > 6}
							>
								<CodeBlockHeader>
									<CodeBlockTitle>
										<CodeBlockFilename>{language}</CodeBlockFilename>
									</CodeBlockTitle>
									<CodeBlockActions>
										<CodeBlockCopyButton />
									</CodeBlockActions>
								</CodeBlockHeader>
							</CodeBlock>
						);
					},
					pre({ children }) {
						return <>{children}</>;
					},
				}}
				remarkPlugins={[remarkGfm]}
			>
				{content}
			</ReactMarkdown>
		</div>
	);
}
