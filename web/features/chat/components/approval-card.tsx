"use client";

import { CheckIcon, ShieldIcon, XIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { useChatStore } from "../store";
import type { ApprovalBatch } from "../types";
import {
	type ApprovalSelections,
	type ApprovalSubmissionDecision,
	isApprovalReadOnly,
	toApprovalDecisionLabel,
} from "./approval-card-state";

type ApprovalCardProps = {
	batch: ApprovalBatch;
	conversationId: string;
	variant?: "timeline" | "floating";
};

const formatJson = (value: Record<string, unknown>) =>
	JSON.stringify(value, null, 2);

const formatDateTime = (value: string | undefined) => {
	if (!value) {
		return "未知";
	}

	const date = new Date(value);
	if (Number.isNaN(date.getTime())) {
		return value;
	}

	return date.toLocaleString("zh-CN", {
		dateStyle: "medium",
		timeStyle: "short",
	});
};

function getBatchStatusText(batch: ApprovalBatch) {
	if (batch.resolutionSource === "timeout") {
		return "30 分钟未处理，已自动拒绝";
	}

	if (batch.status === "resolved") {
		return "审批已提交";
	}

	if (batch.status === "expired") {
		return "审批已过期";
	}

	return "等待人工审批";
}

export function ApprovalCard({
	batch,
	conversationId,
	variant = "timeline",
}: ApprovalCardProps) {
	const submitApproval = useChatStore((state) => state.submitApproval);
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [submittingDecision, setSubmittingDecision] = useState<
		ApprovalSubmissionDecision | undefined
	>();
	const readOnly = isApprovalReadOnly(batch);
	const statusText = useMemo(() => getBatchStatusText(batch), [batch]);

	const isFloating = variant === "floating";
	const immediateDisabled =
		isSubmitting || readOnly || batch.requests.length === 0;
	const decisionButtonsClassName = "grid grid-cols-2 gap-3";

	const submitImmediateDecision = async (
		decision: ApprovalSubmissionDecision,
	) => {
		if (immediateDisabled) {
			return;
		}

		const nextSelections = Object.fromEntries(
			batch.requests.map((request) => [request.id, decision]),
		) as ApprovalSelections;

		setIsSubmitting(true);
		setSubmittingDecision(decision);
		try {
			await submitApproval(batch.id, nextSelections);
		} finally {
			setIsSubmitting(false);
			setSubmittingDecision(undefined);
		}
	};

	return (
		<div
			aria-label={`审批批次 ${batch.id}`}
			className={cn(
				"text-sm",
				isFloating
					? "max-h-[min(24rem,48vh)] overflow-auto rounded-2xl border border-zinc-200 bg-white/95 p-3 shadow-[0_18px_54px_rgba(15,23,42,0.18)] backdrop-blur"
					: "rounded-2xl border border-amber-200 bg-amber-50/60 p-4 shadow-sm",
			)}
			data-conversation-id={conversationId}
			data-variant={variant}
			role="group"
		>
			<div className="flex items-start justify-between gap-3">
				<div className="flex min-w-0 items-start gap-2.5">
					<span
						className={cn(
							"mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full",
							isFloating
								? "bg-zinc-950 text-white"
								: "bg-amber-100 text-amber-900",
						)}
					>
						<ShieldIcon className="size-4" />
					</span>
					<div className="min-w-0">
						<p
							className={cn(
								"font-semibold",
								isFloating ? "text-zinc-950" : "text-amber-950",
							)}
						>
							{isFloating ? "待审批工具" : statusText}
						</p>
						<p
							className={cn(
								"text-xs",
								isFloating ? "text-zinc-500" : "text-amber-800/80",
							)}
						>
							{isFloating
								? `${batch.requests.length} 个工具请求 · 过期 ${formatDateTime(batch.expiresAt)}`
								: `过期时间：${formatDateTime(batch.expiresAt)}`}
						</p>
					</div>
				</div>
				{readOnly ? (
					<span className="shrink-0 rounded-full bg-white px-2.5 py-1 font-medium text-amber-900 text-xs ring-1 ring-amber-200">
						只读历史
					</span>
				) : null}
			</div>

			<div
				className={cn(
					isFloating ? "mt-3 divide-y divide-zinc-100" : "mt-4 space-y-3",
				)}
			>
				{batch.requests.map((request) => (
					<div
						className={cn(
							isFloating
								? "space-y-3 py-3 first:pt-0 last:pb-0"
								: "rounded-xl border border-amber-200 bg-white p-3",
						)}
						key={request.id}
					>
						{isFloating ? (
							<>
								<div className="min-w-0">
									<p className="truncate font-semibold text-lg text-zinc-950">
										{request.toolName}
									</p>
									<p className="text-sm text-zinc-500">
										状态：{toApprovalDecisionLabel(request.decision)}
									</p>
								</div>
								{readOnly ? (
									<p className="font-medium text-zinc-700 text-sm">
										最终结果：{toApprovalDecisionLabel(request.decision)}
									</p>
								) : null}
							</>
						) : (
							<div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
								<div className="min-w-0">
									<p className="truncate font-medium text-zinc-950">
										工具：{request.toolName}
									</p>
									<p className="text-zinc-500 text-xs">
										状态：{toApprovalDecisionLabel(request.decision)}
									</p>
								</div>
								{readOnly ? (
									<p className="font-medium text-zinc-700 text-sm">
										最终结果：{toApprovalDecisionLabel(request.decision)}
									</p>
								) : null}
							</div>
						)}

						<pre
							className={cn(
								"overflow-auto rounded-lg bg-zinc-950 text-white text-xs",
								isFloating ? "max-h-28 p-3" : "mt-3 max-h-56 p-3",
							)}
						>
							{formatJson(request.args)}
						</pre>

						{readOnly ? null : (
							<fieldset
								className={cn(!isFloating && "mt-3", decisionButtonsClassName)}
								data-decision-layout={isFloating ? "banner" : "inline"}
							>
								<legend className="sr-only">工具：{request.toolName}</legend>
								<ImmediateDecisionButton
									disabled={immediateDisabled}
									isSubmitting={submittingDecision === "approve"}
									label="批准"
									layout="banner"
									onClick={() => void submitImmediateDecision("approve")}
									value="approve"
								/>
								<ImmediateDecisionButton
									disabled={immediateDisabled}
									isSubmitting={submittingDecision === "reject"}
									label="拒绝"
									layout="banner"
									onClick={() => void submitImmediateDecision("reject")}
									value="reject"
								/>
							</fieldset>
						)}
					</div>
				))}
			</div>
		</div>
	);
}

function ImmediateDecisionButton({
	disabled,
	isSubmitting,
	label,
	layout = "inline",
	onClick,
	value,
}: {
	disabled: boolean;
	isSubmitting: boolean;
	label: string;
	layout?: "inline" | "banner";
	onClick: () => void;
	value: ApprovalSubmissionDecision;
}) {
	const isBanner = layout === "banner";

	return (
		<button
			className={cn(
				"inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl border font-semibold transition-all focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
				isBanner ? "h-12 w-full px-4 text-base" : "h-10 min-w-24 px-4 text-sm",
				value === "approve" &&
					"border-emerald-700 bg-emerald-700 text-white shadow-[0_10px_24px_rgba(4,120,87,0.20)] hover:bg-emerald-800",
				value === "reject" &&
					"border-rose-200 bg-rose-50 text-rose-800 hover:border-rose-300 hover:bg-rose-100",
			)}
			data-approval-option={value}
			disabled={disabled}
			onClick={onClick}
			type="button"
		>
			{value === "approve" ? (
				<CheckIcon className={cn(isBanner ? "size-4" : "size-3.5")} />
			) : (
				<XIcon className={cn(isBanner ? "size-4" : "size-3.5")} />
			)}
			{isSubmitting ? `${label}中` : label}
		</button>
	);
}
