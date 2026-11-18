import { execFile } from "node:child_process";
import type { IncomingMessage } from "node:http";
import { resolve } from "node:path";
import { promisify } from "node:util";
import type { Plugin } from "vite";

const runFile = promisify(execFile);
const loopback = new Set(["127.0.0.1", "::1", "::ffff:127.0.0.1"]);
const hostnames = new Set(["127.0.0.1", "localhost", "[::1]"]);
const frozenPlan = "e81c73a2b850d9b2b9a3a07a230c80e850428d6367a8d5a3a332fb4c467ebaea";

export function permitsLocalPilotAccess(request: IncomingMessage, method: "GET" | "PUT" | "POST"): boolean {
  if (!loopback.has(request.socket.remoteAddress ?? "") || request.method !== method) return false;
  try {
    const host = request.headers.host;
    if (!host) return false;
    const address = new URL(`http://${host}`);
    if (!hostnames.has(address.hostname) || address.host !== host || address.pathname !== "/") return false;
    if (request.headers.origin && request.headers.origin !== address.origin) return false;
    if (method !== "GET" && (request.headers.origin !== address.origin
      || request.headers["content-type"]?.split(";")[0].trim() !== "application/json")) return false;
    const site = request.headers["sec-fetch-site"];
    return !site || site === "same-origin" || site === "none";
  } catch {
    return false;
  }
}

export function permitsLocalPilotRead(request: IncomingMessage): boolean {
  return permitsLocalPilotAccess(request, "GET");
}

export function tipstersPilot(): Plugin {
  let root = process.cwd();
  const pending = new Map<string, Promise<string>>();
  let saving = false;
  const execute = async (sources: boolean, input?: string) => {
    const repository = resolve(root, "..");
    const python = process.env.ROBIN_TIPSTERS_PYTHON ?? resolve(
      repository, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
    );
    const script = sources ? "tipsters_source_settings.py" : "read-tipsters-pilot.py";
    const args = sources ? [
      "--settings-directory", process.env.ROBIN_TIPSTERS_SETTINGS_DIRECTORY ?? resolve(root, ".ci/tipsters-source-config"),
      ...(input ? ["--update"] : []),
    ] : [
      "--pilot-directory", process.env.ROBIN_TIPSTERS_DIRECTORY ?? resolve(repository, "..", "pilote-tipsters-j12"),
      "--plan-sha256", process.env.ROBIN_TIPSTERS_PLAN_SHA256 ?? frozenPlan,
    ];
    const execution = runFile(python, ["-X", "utf8", "-B", resolve(root, "scripts", script), ...args],
      { timeout: 8_000, maxBuffer: 8_000_000, windowsHide: true, encoding: "utf8" });
    execution.child.stdin?.end(input);
    return (await execution).stdout;
  };
  const middleware = async (
    request: IncomingMessage,
    response: import("node:http").ServerResponse,
    next: () => void,
  ) => {
    const path = request.url?.split("?")[0];
    const sources = path === "/api/tipsters/sources";
    if (!sources && path !== "/api/tipsters") return next();
    const write = sources && request.method === "PUT";
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("Content-Type", "application/json; charset=utf-8");
    response.setHeader("X-Content-Type-Options", "nosniff");
    if (!permitsLocalPilotAccess(request, write ? "PUT" : "GET")) {
      response.statusCode = 403;
      response.end(JSON.stringify({ status: "forbidden", message: "Accès local requis sur A9_Mega." }));
      return;
    }
    if (write && saving) {
      response.statusCode = 409;
      response.end(JSON.stringify({ status: "conflict", message: "Une sauvegarde est en cours. Votre brouillon est conservé." }));
      return;
    }
    const length = Number(request.headers["content-length"]);
    if (write && (!Number.isInteger(length) || length < 1 || length > 16_384)) {
      response.statusCode = 413;
      response.end(JSON.stringify({ status: "invalid", message: "Le paramétrage dépasse la taille autorisée." }));
      return;
    }
    try {
      if (write) {
        saving = true;
        const timer = setTimeout(() => request.destroy(), 5_000);
        let input: string;
        try {
          const chunks: Buffer[] = [];
          let size = 0;
          for await (const chunk of request) {
            const buffer = Buffer.from(chunk);
            size += buffer.length;
            if (size > 16_384) throw new Error("body limit");
            chunks.push(buffer);
          }
          input = Buffer.concat(chunks).toString("utf8");
        } finally {
          clearTimeout(timer);
        }
        const result = await execute(true, input);
        pending.delete("sources");
        const status = JSON.parse(result).status;
        response.statusCode = status === "saved" ? 200 : status === "conflict" ? 409 : 400;
        response.end(result);
      } else {
        const key = sources ? "sources" : "pilot";
        if (!pending.has(key)) {
          const task: Promise<string> = execute(sources).finally(() => {
            if (pending.get(key) === task) pending.delete(key);
          });
          pending.set(key, task);
        }
        response.end(await pending.get(key));
      }
    } catch {
      response.statusCode = 503;
      response.end(JSON.stringify({ status: "unavailable", message: "La lecture locale du pilote est indisponible." }));
    } finally {
      if (write) saving = false;
    }
  };
  return {
    name: "robin-local-tipsters-pilot",
    configResolved(config) { root = config.root; },
    configureServer(server) { server.middlewares.use(middleware); },
    configurePreviewServer(server) { server.middlewares.use(middleware); },
  };
}
