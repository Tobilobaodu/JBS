import path from "node:path";
import { fileURLToPath } from "node:url";

// .mjs has no __dirname; derive it so the paths below are absolute.
const projectRoot = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emits a self-contained server bundle at .next/standalone, including only
  // the subset of node_modules actually reached. The production Dockerfile
  // copies that instead of the full dependency tree.
  output: "standalone",

  // ───────────────────────────────────────────────────────────────────
  // Both of these pin the workspace root to THIS directory. Without them
  // Next walks upward, finds the stray (untracked) package-lock.json at
  // the repo root, infers that as the root, and nests the standalone
  // output at .next/standalone/frontend/server.js instead of
  // .next/standalone/server.js — which breaks the Dockerfile's
  // `CMD ["node", "server.js"]`.
  //
  // It is worth pinning rather than deleting that lockfile: the layout
  // would otherwise depend on whether a parent directory happens to
  // contain a lockfile, which differs between a local build and Docker's
  // frontend-only build context.
  //
  // outputFileTracingRoot governs the standalone/tracing layout;
  // turbopack.root governs module resolution and silences the inference
  // warning. They are separate settings and both matter here.
  // ───────────────────────────────────────────────────────────────────
  outputFileTracingRoot: projectRoot,
  turbopack: {
    root: projectRoot,
  },
};

export default nextConfig;
