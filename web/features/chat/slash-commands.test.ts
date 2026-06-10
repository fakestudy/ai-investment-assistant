import assert from "node:assert/strict";
import test from "node:test";
import {
	getNextSlashCommandIndex,
	getSlashCommandSuggestions,
	isExactSlashCommand,
} from "./slash-commands";

test("slash command suggestions expose get-balance for slash prefixes", () => {
	assert.deepEqual(
		getSlashCommandSuggestions("/").map((command) => command.value),
		["/get-balance"],
	);
	assert.deepEqual(
		getSlashCommandSuggestions("/get").map((command) => command.value),
		["/get-balance"],
	);
});

test("get-balance is an exact chat slash command", () => {
	assert.equal(isExactSlashCommand("/get-balance"), true);
	assert.equal(isExactSlashCommand(" /get-balance "), true);
	assert.equal(isExactSlashCommand("/get"), false);
});

test("slash command suggestions stay scoped to the first token", () => {
	assert.deepEqual(getSlashCommandSuggestions("hello /"), []);
	assert.deepEqual(getSlashCommandSuggestions("/get-balance now"), []);
	assert.deepEqual(getSlashCommandSuggestions("/unknown"), []);
});

test("slash command navigation wraps through multiple candidates", () => {
	assert.equal(
		getNextSlashCommandIndex({
			currentIndex: 0,
			direction: "next",
			itemCount: 3,
		}),
		1,
	);
	assert.equal(
		getNextSlashCommandIndex({
			currentIndex: 2,
			direction: "next",
			itemCount: 3,
		}),
		0,
	);
	assert.equal(
		getNextSlashCommandIndex({
			currentIndex: 0,
			direction: "previous",
			itemCount: 3,
		}),
		2,
	);
});

test("slash command navigation ignores empty candidate lists", () => {
	assert.equal(
		getNextSlashCommandIndex({
			currentIndex: 1,
			direction: "next",
			itemCount: 0,
		}),
		0,
	);
});
