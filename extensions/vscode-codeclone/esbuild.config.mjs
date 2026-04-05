import {build, context} from "esbuild";

const watch = process.argv.includes("--watch");

const options = {
    entryPoints: ["src/extension.js"],
    outfile: "dist/extension.js",
    bundle: true,
    platform: "node",
    format: "cjs",
    target: "node20",
    external: ["vscode"],
    sourcemap: true,
    legalComments: "none",
    logLevel: "info",
    treeShaking: true,
    packages: "external",
};

if (watch) {
    const ctx = await context(options);
    await ctx.watch();
} else {
    await build(options);
}
