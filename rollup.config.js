import deckyPlugin from "@decky/rollup";
import ts from "typescript";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";

const config = deckyPlugin({});

// Keep Decky's Steam externals and packaging preset. Transpile each file without
// the preset's TypeScript watch program, which leaks deferred macOS watchers on
// TS 5.9 / Node 26 even for one-shot builds. `npm run build` checks types first.
config.plugins = config.plugins.map(plugin => plugin.name === "typescript" ? {
  name: "decky-agent-typescript",
  resolveId(source, importer) {
    if (!source.startsWith(".") || !importer) return null;
    const base = resolve(dirname(importer), source);
    return [base + ".ts", base + ".tsx", resolve(base, "index.ts"), resolve(base, "index.tsx")]
      .find(path => existsSync(path)) || null;
  },
  transform(source, id) {
    if (!/\.tsx?$/.test(id)) return null;
    const output = ts.transpileModule(source, {
      fileName: id,
      compilerOptions: {
        target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext,
        jsx: ts.JsxEmit.ReactJSX, sourceMap: true, inlineSources: true,
      },
    });
    return { code: output.outputText, map: output.sourceMapText };
  },
} : plugin);

export default config;
