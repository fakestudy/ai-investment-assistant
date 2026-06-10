export type ChatSlashCommand = {
	value: string;
	label: string;
	description: string;
};

export type SlashCommandNavigationDirection = "next" | "previous";

export const chatSlashCommands: ChatSlashCommand[] = [
	{
		value: "/get-balance",
		label: "DeepSeek 余额",
		description: "查询当前 DeepSeek API 账户余额",
	},
];

export function getSlashCommandSuggestions(input: string): ChatSlashCommand[] {
	if (!input.startsWith("/")) {
		return [];
	}

	const query = input.trim();
	if (query.includes(" ")) {
		return [];
	}

	return chatSlashCommands.filter((command) => command.value.startsWith(query));
}

export function isExactSlashCommand(input: string): boolean {
	const query = input.trim();
	return chatSlashCommands.some((command) => command.value === query);
}

export function getNextSlashCommandIndex({
	currentIndex,
	direction,
	itemCount,
}: {
	currentIndex: number;
	direction: SlashCommandNavigationDirection;
	itemCount: number;
}): number {
	if (itemCount <= 0) {
		return 0;
	}

	if (direction === "next") {
		return (currentIndex + 1) % itemCount;
	}

	return (currentIndex - 1 + itemCount) % itemCount;
}
