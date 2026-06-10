import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const webRoot = path.resolve(import.meta.dirname, "..");
const packageJsonPath = path.join(webRoot, "package.json");
const binPath = path.join(webRoot, "bin/aia.mjs");

test("package exposes aia command bin", async () => {
	const packageJson = JSON.parse(await readFile(packageJsonPath, "utf8")) as {
		bin?: Record<string, string>;
		scripts?: Record<string, string>;
	};

	assert.equal(packageJson.bin?.aia, "bin/aia.mjs");
	assert.equal(packageJson.scripts?.aia, "node bin/aia.mjs");
});

test("aia bin is executable and boots the Ink CLI entrypoint", async () => {
	const bin = await readFile(binPath, "utf8");
	const mode = (await stat(binPath)).mode;

	assert.ok(bin.startsWith("#!/usr/bin/env node"));
	assert.ok(bin.includes("cli/main.tsx"));
	assert.notEqual(mode & 0o111, 0);
});

test("ChatCliApp module loads with current API dependencies", async () => {
	const module = await import("./app");

	assert.equal(typeof module.ChatCliApp, "function");
});
