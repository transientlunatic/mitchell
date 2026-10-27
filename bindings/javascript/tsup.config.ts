import { defineConfig } from "tsup";

export default defineConfig({
  entry: { index: "src/index.ts", node: "src/node.ts" },
  format: ["esm", "cjs"],
  dts: true,
  clean: true,
  external: ["zarrita", "@zarrita/storage"],
});
