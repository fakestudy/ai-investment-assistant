#!/usr/bin/env node
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const binDir = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(binDir, "..");
const cliEntry = resolve(webRoot, "cli/main.tsx");

const child = spawn(process.execPath, ["--import", "tsx", cliEntry], {
	cwd: webRoot,
	env: process.env,
	stdio: "inherit",
});

child.on("error", (error) => {
	console.error(error instanceof Error ? error.message : String(error));
	process.exitCode = 1;
});

child.on("exit", (code, signal) => {
	if (signal) {
		process.kill(process.pid, signal);
		return;
	}

	process.exitCode = code ?? 0;
});
