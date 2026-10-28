import { build } from "esbuild";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
await mkdir(join(root, ".preview"), { recursive: true });
const temp = await mkdtemp(join(root, ".preview/auth-view-"));
try {
  const output = join(temp, "test.mjs");
  await build({
    entryPoints: [join(root, "tests/auth-view.tsx")], outfile: output,
    bundle: true, platform: "node", format: "esm", packages: "external",
    alias: { "@decky/ui": join(root, "src/preview/ui.tsx"), "@decky/api": join(root, "src/preview/api.ts") },
    logLevel: "error",
  });
  await import(pathToFileURL(output).href);
} finally {
  await rm(temp, { recursive: true, force: true });
}
