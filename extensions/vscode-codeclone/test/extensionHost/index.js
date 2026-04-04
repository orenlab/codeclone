"use strict";

const assert = require("node:assert/strict");
const vscode = require("vscode");

async function run() {
  const extension = vscode.extensions.getExtension("orenlab.codeclone");
  assert.ok(extension, "Expected orenlab.codeclone extension to be registered.");

  await extension.activate();

  const packageJson = extension.packageJSON;
  assert.equal(packageJson.name, "codeclone");
  assert.equal(
    packageJson.capabilities.untrustedWorkspaces.supported,
    "limited",
    "Expected Restricted Mode support to be limited."
  );
  assert.deepEqual(
    [...packageJson.capabilities.untrustedWorkspaces.restrictedConfigurations].sort(),
    ["codeclone.mcp.args", "codeclone.mcp.command"]
  );

  const commandList = await vscode.commands.getCommands(true);
  for (const command of [
    "codeclone.manageWorkspaceTrust",
    "codeclone.analyzeWorkspace",
    "codeclone.analyzeChangedFiles",
    "codeclone.reviewPriorityQueue",
    "codeclone.openSetupHelp",
    "codeclone.showHelpTopic",
  ]) {
    assert.ok(
      commandList.includes(command),
      `Expected command ${command} to be registered.`
    );
  }

  const viewIds = packageJson.contributes.views.codeclone.map((view) => view.id);
  assert.deepEqual(viewIds, [
    "codeclone.overview",
    "codeclone.hotspots",
    "codeclone.session",
  ]);

  await vscode.commands.executeCommand("codeclone.openOverview");

  if (typeof extension.exports?.deactivate === "function") {
    await extension.exports.deactivate();
  }
}

module.exports = { run };
