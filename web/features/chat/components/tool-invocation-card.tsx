"use client";

import { useEffect, useState } from "react";
import {
	Tool,
	ToolContent,
	ToolHeader,
	ToolInput,
	ToolOutput,
} from "@/components/ai-elements/tool";
import type { ToolInvocation } from "../types";
import {
	getToolInvocationCardOpenState,
	getToolInvocationStatusSummary,
} from "./tool-invocation-card-state";

type ToolInvocationCardProps = {
	hideHeaderIcon?: boolean;
	invocation: ToolInvocation;
};

const statusLabels: Record<ToolInvocation["status"], string> = {
	running: "Running",
	completed: "Completed",
	error: "Error",
	awaiting_approval: "Awaiting Approval",
	rejected: "Rejected",
	expired: "Expired",
};

export function toToolState(status: ToolInvocation["status"]) {
	if (status === "awaiting_approval") {
		return "approval-requested" as const;
	}

	if (status === "rejected" || status === "expired") {
		return "output-denied" as const;
	}

	if (status === "running") {
		return "input-available" as const;
	}

	if (status === "error") {
		return "output-error" as const;
	}

	return "output-available" as const;
}

function summarizeResult(result: unknown) {
	if (result === undefined || result === null) {
		return "No result yet";
	}

	if (typeof result === "string") {
		const trimmed = result.trim();
		return trimmed ? trimmed.slice(0, 180) : "Empty result";
	}

	if (typeof result === "number" || typeof result === "boolean") {
		return String(result);
	}

	if (Array.isArray(result)) {
		return `${result.length} result item${result.length === 1 ? "" : "s"}`;
	}

	if (typeof result === "object") {
		const record = result as Record<string, unknown>;
		const summary = record.summary ?? record.title ?? record.message;

		if (typeof summary === "string" && summary.trim()) {
			return summary.trim().slice(0, 180);
		}

		const keys = Object.keys(record);
		return keys.length > 0
			? `${keys.length} result field${keys.length === 1 ? "" : "s"}: ${keys.slice(0, 4).join(", ")}`
			: "Empty result object";
	}

	return "Result available";
}

export function ToolInvocationCard({
	hideHeaderIcon = false,
	invocation,
}: ToolInvocationCardProps) {
	const hasError = invocation.status === "error" && Boolean(invocation.error);
	const resultSummary = hasError
		? invocation.error
		: invocation.result === undefined
			? getToolInvocationStatusSummary(invocation.status)
			: summarizeResult(invocation.result);
	const [isOpen, setIsOpen] = useState(() =>
		getToolInvocationCardOpenState(invocation.status),
	);

	useEffect(() => {
		setIsOpen(getToolInvocationCardOpenState(invocation.status));
	}, [invocation.id, invocation.status]);

	return (
		<Tool
			className="mb-0 border-zinc-200 bg-zinc-50/80 shadow-sm"
			onOpenChange={setIsOpen}
			open={isOpen}
		>
			<ToolHeader
				state={toToolState(invocation.status)}
				showIcon={!hideHeaderIcon}
				toolName={invocation.toolName}
				type="dynamic-tool"
			/>
			<ToolContent className="space-y-3">
				<div className="grid gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs sm:grid-cols-3">
					<div>
						<p className="font-medium text-zinc-500">Tool</p>
						<p className="mt-1 break-all text-zinc-900">
							{invocation.toolName}
						</p>
					</div>
					<div>
						<p className="font-medium text-zinc-500">Status</p>
						<p className="mt-1 text-zinc-900">
							{statusLabels[invocation.status]}
						</p>
					</div>
					<div>
						<p className="font-medium text-zinc-500">Latency</p>
						<p className="mt-1 text-zinc-900">
							{typeof invocation.latencyMs === "number"
								? `${invocation.latencyMs}ms`
								: "Pending"}
						</p>
					</div>
				</div>

				<ToolInput input={invocation.args} />

				<div className="rounded-lg border border-zinc-200 bg-white px-3 py-2">
					<p className="font-medium text-zinc-500 text-xs uppercase tracking-wide">
						Summary
					</p>
					<p className="mt-1 text-sm text-zinc-800 wrap-break-word">
						{resultSummary}
					</p>
				</div>

				<ToolOutput errorText={invocation.error} output={invocation.result} />
			</ToolContent>
		</Tool>
	);
}
