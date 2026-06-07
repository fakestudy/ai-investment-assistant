"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useChatStore } from "../store";
import type { ApprovalBatch } from "../types";
import {
	type ApprovalSelections,
	type ApprovalSubmissionDecision,
	canSubmitApproval,
	isApprovalReadOnly,
	toApprovalDecisionLabel,
} from "./approval-card-state";

type ApprovalCardProps = {
	batch: ApprovalBatch;
	conversationId: string;
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

export function ApprovalCard({ batch, conversationId }: ApprovalCardProps) {
	const submitApproval = useChatStore((state) => state.submitApproval);
	const [selections, setSelections] = useState<ApprovalSelections>({});
	const [isSubmitting, setIsSubmitting] = useState(false);
	const readOnly = isApprovalReadOnly(batch);
	const submitDisabled =
		isSubmitting || readOnly || !canSubmitApproval(batch, selections);
	const statusText = useMemo(() => getBatchStatusText(batch), [batch]);

	const choose = (requestId: string, decision: ApprovalSubmissionDecision) => {
		setSelections((current) => ({
			...current,
			[requestId]: decision,
		}));
	};

	const submit = async () => {
		if (submitDisabled) {
			return;
		}

		setIsSubmitting(true);
		try {
			await submitApproval(batch.id, selections);
		} finally {
			setIsSubmitting(false);
		}
	};

	return (
		<div
			aria-label={`审批批次 ${batch.id}`}
			className="rounded-2xl border border-amber-200 bg-amber-50/60 p-4 text-sm shadow-sm"
			data-conversation-id={conversationId}
			role="group"
		>
			<div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
				<div>
					<p className="font-semibold text-amber-950">{statusText}</p>
					<p className="text-amber-800/80 text-xs">
						过期时间：{formatDateTime(batch.expiresAt)}
					</p>
				</div>
				{readOnly ? (
					<span className="rounded-full bg-white px-2.5 py-1 font-medium text-amber-900 text-xs ring-1 ring-amber-200">
						只读历史
					</span>
				) : null}
			</div>

			<div className="mt-4 space-y-3">
				{batch.requests.map((request) => (
					<div
						className="rounded-xl border border-amber-200 bg-white p-3"
						key={request.id}
					>
						<div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
							<div>
								<p className="font-medium text-zinc-950">
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
							) : (
								<fieldset className="flex gap-2">
									<legend className="sr-only">工具：{request.toolName}</legend>
									<DecisionButton
										disabled={isSubmitting}
										isSelected={selections[request.id] === "approve"}
										label="批准"
										name={`approval-${request.id}`}
										onChange={() => choose(request.id, "approve")}
										value="approve"
									/>
									<DecisionButton
										disabled={isSubmitting}
										isSelected={selections[request.id] === "reject"}
										label="拒绝"
										name={`approval-${request.id}`}
										onChange={() => choose(request.id, "reject")}
										value="reject"
									/>
								</fieldset>
							)}
						</div>

						<pre className="mt-3 max-h-56 overflow-auto rounded-lg bg-zinc-950 p-3 text-white text-xs">
							{formatJson(request.args)}
						</pre>
					</div>
				))}
			</div>

			{readOnly ? null : (
				<div className="mt-4 flex justify-end">
					<Button disabled={submitDisabled} onClick={submit} type="button">
						{isSubmitting ? "提交中" : "提交审批"}
					</Button>
				</div>
			)}
		</div>
	);
}

function DecisionButton({
	disabled,
	isSelected,
	label,
	name,
	onChange,
	value,
}: {
	disabled: boolean;
	isSelected: boolean;
	label: string;
	name: string;
	onChange: () => void;
	value: ApprovalSubmissionDecision;
}) {
	return (
		<label>
			<input
				checked={isSelected}
				className="peer sr-only"
				disabled={disabled}
				name={name}
				onChange={onChange}
				type="radio"
				value={value}
			/>
			<span
				className={cn(
					"inline-flex h-7 min-w-16 cursor-pointer items-center justify-center rounded-lg border border-transparent bg-secondary px-2.5 font-medium text-[0.8rem] text-secondary-foreground transition-all peer-focus-visible:border-ring peer-focus-visible:ring-3 peer-focus-visible:ring-ring/50 peer-disabled:pointer-events-none peer-disabled:cursor-not-allowed peer-disabled:opacity-50",
					isSelected && "border-amber-700 bg-amber-100 text-amber-950",
				)}
			>
				{label}
			</span>
		</label>
	);
}
