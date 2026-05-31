import assert from "node:assert/strict";
import test from "node:test";
import { normalizeMarkdownCodeLanguage } from "./chat-markdown";

test("normalizeMarkdownCodeLanguage extracts fence language classes", () => {
	assert.equal(normalizeMarkdownCodeLanguage("language-tsx"), "tsx");
	assert.equal(
		normalizeMarkdownCodeLanguage("language-typescript"),
		"typescript",
	);
});

test("normalizeMarkdownCodeLanguage falls back to text for empty classes", () => {
	assert.equal(normalizeMarkdownCodeLanguage(undefined), "text");
	assert.equal(normalizeMarkdownCodeLanguage(""), "text");
});
