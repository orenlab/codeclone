import {mkdir, readFile, rm} from "node:fs/promises";
import path from "node:path";
import {execFile} from "node:child_process";
import {promisify} from "node:util";
import {fileURLToPath} from "node:url";

const execFileAsync = promisify(execFile);
const packageDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.dirname(packageDir);
const manifestPath = path.join(rootDir, "manifest.json");
const distDir = path.join(rootDir, "dist");

/**
 * @param {string[]} argv
 * @returns {string}
 */
function resolveOutputPath(argv) {
    const explicitIndex = argv.indexOf("--out");
    if (explicitIndex !== -1) {
        const explicitPath = argv[explicitIndex + 1];
        if (!explicitPath) {
            throw new Error("--out requires a value.");
        }
        return path.resolve(rootDir, explicitPath);
    }
    return path.join(distDir, "codeclone-claude-desktop.mcpb");
}

async function loadManifest() {
    return JSON.parse(await readFile(manifestPath, "utf8"));
}

function validateManifest(manifest) {
    if (!manifest || typeof manifest !== "object") {
        throw new Error("manifest.json must contain a JSON object.");
    }
    if (typeof manifest.manifest_version !== "string" || !manifest.manifest_version) {
        throw new Error("manifest.json must declare manifest_version.");
    }
    if (typeof manifest.name !== "string" || !manifest.name) {
        throw new Error("manifest.json must declare a bundle name.");
    }
    if (typeof manifest.version !== "string" || !manifest.version) {
        throw new Error("manifest.json must declare a bundle version.");
    }
    if (manifest.server?.type !== "node") {
        throw new Error("manifest.json must use a node server entry.");
    }
    if (typeof manifest.server?.entry_point !== "string" || !manifest.server.entry_point) {
        throw new Error("manifest.json must declare server.entry_point.");
    }
    if (typeof manifest.server?.mcp_config?.command !== "string") {
        throw new Error("manifest.json must declare server.mcp_config.command.");
    }
    if (!Array.isArray(manifest.server?.mcp_config?.args)) {
        throw new Error("manifest.json must declare server.mcp_config.args as an array.");
    }
    if (!Array.isArray(manifest.tools) || manifest.tools.length === 0) {
        throw new Error("manifest.json must declare at least one tool.");
    }
    return manifest;
}

async function main(argv = process.argv.slice(2)) {
    const outPath = resolveOutputPath(argv);
    validateManifest(await loadManifest());
    await mkdir(distDir, {recursive: true});
    await rm(outPath, {force: true});

    const bundleEntries = [
        "manifest.json",
        "server",
        "src",
        "media",
        "README.md",
        "LICENSE",
        "package.json",
    ];

    await execFileAsync(
        "zip",
        ["-X", "-q", "-r", outPath, ...bundleEntries],
        {cwd: rootDir},
    );

    process.stdout.write(`Created ${outPath} from ${manifestPath}\n`);
}

const isDirectRun =
    process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isDirectRun) {
    await main();
}

export {main, resolveOutputPath, validateManifest};
