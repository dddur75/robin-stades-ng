import { execFile } from "node:child_process";
import type { IncomingMessage } from "node:http";
import { resolve } from "node:path";
import { promisify } from "node:util";
import type { Plugin } from "vite";

const runFile = promisify(execFile);
const loopback = new Set(["127.0.0.1", "::1", "::ffff:127.0.0.1"]);
const hostnames = new Set(["127.0.0.1", "localhost", "[::1]"]);
const frozenPlan = "e81c73a2b850d9b2b9a3a07a230c80e850428d6367a8d5a3a332fb4c467ebaea";

export function permitsLocalPilotRead(request: IncomingMessage): boolean {
  if (!loopback.has(request.socket.remoteAddress ?? "") || request.method !== "GET") return false;
  try {
    const host = request.headers.host;
    if (!host) return false;
    const address = new URL(`http://${host}`);
    if (!hostnames.has(address.hostname) || address.host !== host || address.pathname !== "/") return false;
    if (request.headers.origin && request.headers.origin !== address.origin) return false;
    const site = request.headers["sec-fetch-site"];
    return !site || site === "same-origin" || site === "none";
  } catch {
    return false;
  }
}

export function tipstersPilot(): Plugin {
  let root = process.cwd();
  let pending: Promise<string> | undefined;
  const middleware = async (
    request: IncomingMessage,
    response: import("node:http").ServerResponse,
    next: () => void,
  ) => {
    if (request.url?.split("?")[0] !== "/api/tipsters") return next();
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("Content-Type", "application/json; charset=utf-8");
    response.setHeader("X-Content-Type-Options", "nosniff");
    if (!permitsLocalPilotRead(request)) {
      response.statusCode = 403;
      response.end(JSON.stringify({ status: "forbidden", message: "Accès local requis sur A9_Mega." }));
      return;
    }
    try {
      if (!pending) {
        const repository = resolve(root, "..");
        const python = process.env.ROBIN_TIPSTERS_PYTHON ?? resolve(
          repository, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
        );
        const directory = process.env.ROBIN_TIPSTERS_DIRECTORY ?? resolve(repository, "..", "pilote-tipsters-j12");
        const digest = process.env.ROBIN_TIPSTERS_PLAN_SHA256 ?? frozenPlan;
        pending = runFile(python, ["-X", "utf8", "-B", resolve(root, "scripts/read-tipsters-pilot.py"),
          "--pilot-directory", directory, "--plan-sha256", digest],
        { timeout: 8_000, maxBuffer: 8_000_000, windowsHide: true, encoding: "utf8" })
          .then(({ stdout }) => stdout).finally(() => { pending = undefined; });
      }
      response.end(await pending);
    } catch {
      response.statusCode = 503;
      response.end(JSON.stringify({ status: "unavailable", message: "La lecture locale du pilote est indisponible." }));
    }
  };
  return {
    name: "robin-local-tipsters-pilot",
    configResolved(config) { root = config.root; },
    configureServer(server) { server.middlewares.use(middleware); },
    configurePreviewServer(server) { server.middlewares.use(middleware); },
  };
}
