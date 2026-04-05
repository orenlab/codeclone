import {mkdir, rm} from "node:fs/promises";
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

async function main() {
    const outPath = resolveOutputPath(process.argv.slice(2));
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

await main();
