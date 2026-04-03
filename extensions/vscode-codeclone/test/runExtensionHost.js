"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");

function resolveVsCodeCli() {
  const candidates = [
    process.env.VSCODE_CLI,
    "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
    "/Applications/Visual Studio Code - Insiders.app/Contents/Resources/app/bin/code",
  ].filter(Boolean);
  return candidates.find((candidate) => fs.existsSync(candidate)) || null;
}

async function main() {
  const cliPath = resolveVsCodeCli();
  if (!cliPath) {
    throw new Error(
      "Could not find a local VS Code CLI. Set VSCODE_CLI or install Visual Studio Code."
    );
  }

  const extensionDevelopmentPath = path.resolve(__dirname, "..");
  const extensionTestsPath = path.resolve(__dirname, "extensionHost", "index.js");
  const workspaceFolder = extensionDevelopmentPath;
  const userDataDir = fs.mkdtempSync(
    path.join(os.tmpdir(), "codeclone-vscode-test-user-")
  );
  const extensionsDir = fs.mkdtempSync(
    path.join(os.tmpdir(), "codeclone-vscode-test-ext-")
  );

  const args = [
    workspaceFolder,
    "--disable-extensions",
    "--disable-workspace-trust",
    "--skip-welcome",
    "--skip-release-notes",
    `--user-data-dir=${userDataDir}`,
    `--extensions-dir=${extensionsDir}`,
    `--extensionDevelopmentPath=${extensionDevelopmentPath}`,
    `--extensionTestsPath=${extensionTestsPath}`,
  ];

  await new Promise((resolve, reject) => {
    const child = spawn(cliPath, args, {
      stdio: "inherit",
      shell: false,
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`VS Code extension host tests exited with code ${code}.`));
    });
  });
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
