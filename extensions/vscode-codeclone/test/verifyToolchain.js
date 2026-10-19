"use strict";

// CI toolchain gate. Runs after `npm ci --ignore-scripts --include=optional`
// and before the build; exits 1 unless the installed esbuild is exactly the
// one package-lock.json pins and actually works on this runner:
//   - the runner is the expected platform (argument, e.g. `linux-x64`);
//   - node_modules/esbuild and require("esbuild").version equal the lock;
//   - @esbuild/<platform> is locked and installed at that same version;
//   - its binary executes and reports that version;
//   - esbuild.transformSync really transforms code through it.
// Install scripts are skipped, so nothing else proves the binary is usable.
//
// This is the environment contract: it proves what is installed and runs.
// The configuration contract (the exact install command, the checkout's
// `persist-credentials: false`, and this step's place after the install and
// before the build) is a static pin in tests/test_integrations_workflow_contract.py.
// One contract does not replace the other.
//
// Usage: node test/verifyToolchain.js [expected-platform]
// Without an argument the expected platform is the current process's own.

const fs = require("node:fs");
const path = require("node:path");
const {execFileSync} = require("node:child_process");

const ROOT = path.resolve(__dirname, "..");

/**
 * @param {string} message
 * @returns {never}
 */
function fail(message) {
    process.stderr.write(`verify-toolchain: FAIL: ${message}\n`);
    process.exit(1);
}

/** @param {string} relative */
function readJson(relative) {
    const file = path.join(ROOT, relative);
    if (!fs.existsSync(file)) {
        fail(`${relative} is missing`);
    }
    return JSON.parse(fs.readFileSync(file, "utf8"));
}

/**
 * @param {string} what
 * @param {unknown} actual
 * @param {string} locked
 */
function requireLocked(what, actual, locked) {
    if (actual !== locked) {
        fail(`${what} is ${JSON.stringify(actual)}, package-lock.json pins ${locked}`);
    }
}

function main() {
    const runtimePlatform = `${process.platform}-${process.arch}`;
    const expectedPlatform = process.argv[2] || runtimePlatform;
    if (expectedPlatform !== runtimePlatform) {
        fail(`runner platform is ${runtimePlatform}, expected ${expectedPlatform}`);
    }
    if (process.env.ESBUILD_BINARY_PATH) {
        fail("ESBUILD_BINARY_PATH is set; esbuild would bypass the locked binary");
    }

    const lockedPackages = readJson("package-lock.json").packages || {};
    const lockedVersion = (lockedPackages["node_modules/esbuild"] || {}).version;
    if (typeof lockedVersion !== "string") {
        fail("package-lock.json pins no node_modules/esbuild version");
    }
    requireLocked(
        "node_modules/esbuild",
        readJson("node_modules/esbuild/package.json").version,
        lockedVersion,
    );

    const resolved = require.resolve("esbuild");
    if (!resolved.startsWith(path.join(ROOT, "node_modules", "esbuild") + path.sep)) {
        fail(`require("esbuild") resolves outside this extension: ${resolved}`);
    }
    const esbuild = require("esbuild");
    requireLocked('require("esbuild").version', esbuild.version, lockedVersion);

    const platformPackage = `@esbuild/${expectedPlatform}`;
    requireLocked(
        `the lock entry for ${platformPackage}`,
        (lockedPackages[`node_modules/${platformPackage}`] || {}).version,
        lockedVersion,
    );
    requireLocked(
        `installed ${platformPackage}`,
        readJson(`node_modules/${platformPackage}/package.json`).version,
        lockedVersion,
    );

    const binary = path.join(
        ROOT,
        "node_modules",
        platformPackage,
        process.platform === "win32" ? "esbuild.exe" : path.join("bin", "esbuild"),
    );
    let binaryVersion;
    try {
        binaryVersion = execFileSync(binary, ["--version"], {encoding: "utf8"}).trim();
    } catch (error) {
        fail(`${platformPackage} binary does not execute: ${error.message}`);
    }
    requireLocked(`${platformPackage} binary --version`, binaryVersion, lockedVersion);

    const source = "const answer: number = 42;";
    const expected = "const answer = 42;\n";
    let transformed;
    try {
        transformed = esbuild.transformSync(source, {loader: "ts"}).code;
    } catch (error) {
        fail(`esbuild.transformSync failed: ${error.message}`);
    }
    if (transformed !== expected) {
        fail(`esbuild.transformSync returned ${JSON.stringify(transformed)}`);
    }

    process.stdout.write(
        `verify-toolchain: OK esbuild ${lockedVersion} (lock = installed = API = ` +
            `${platformPackage} binary), transformSync ran on ${runtimePlatform}\n`,
    );
}

main();
