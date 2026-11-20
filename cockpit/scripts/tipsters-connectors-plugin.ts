import { execFile } from "node:child_process";
import type { IncomingMessage, ServerResponse } from "node:http";
import { resolve } from "node:path";
import { promisify } from "node:util";
import type { Plugin } from "vite";

import { permitsLocalPilotAccess } from "./tipsters-pilot-plugin";

const runFile = promisify(execFile);

export function connectorDirectory(root:string,writing:boolean,env:Record<string,string|undefined>=process.env):string {
  const own=env.ROBIN_CONNECTORS_DIRECTORY??resolve(root,'.ci/tipsters-connectors');
  return writing?own:env.ROBIN_CONNECTORS_READ_DIRECTORY??own;
}

export function tipstersConnectors(): Plugin {
  let root = process.cwd();
  let running = false;
  let reading: Promise<string> | undefined;
  function execute(sourceId?: string) {
    const repository = resolve(root, "..");
    const python = process.env.ROBIN_TIPSTERS_PYTHON ?? resolve(repository, ".venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
    const args = ["-X", "utf8", "-B", resolve(root, "scripts/run-tipster-connectors.py"),
      "--directory", connectorDirectory(root,Boolean(sourceId))];
    if (sourceId) args.push("--run", ...(sourceId === "all" ? [] : ["--source-id", sourceId]));
    return runFile(python, args, { timeout: sourceId ? 2_760_000 : 8_000,
      maxBuffer: 12_000_000, windowsHide: true, encoding: "utf8" });
  }
  async function middleware(request: IncomingMessage, response: ServerResponse, next: () => void) {
    if (request.url?.split("?")[0] !== "/api/tipsters/connectors") return next();
    const write = request.method === "POST";
    response.setHeader("Content-Type", "application/json; charset=utf-8");
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("X-Content-Type-Options", "nosniff");
    if (!permitsLocalPilotAccess(request, write ? "POST" : "GET")) {
      response.statusCode = 403;
      response.end(JSON.stringify({ status: "forbidden", message: "Accès local sur A9_Mega requis." }));
      return;
    }
    try {
      if (write) {
        if (running) {
          response.statusCode = 409;
          response.end(JSON.stringify({ status: "conflict", message: "Une collecte est déjà en cours." }));
          return;
        }
        const length = Number(request.headers["content-length"]);
        if (!Number.isInteger(length) || length < 1 || length > 1000) throw new Error("body size");
        const chunks: Buffer[] = [];
        let size = 0;
        const timer = setTimeout(() => request.destroy(), 5_000);
        try {
          for await (const part of request) {
            size += Buffer.byteLength(part);
            if (size > 1000) throw new Error("body size");
            chunks.push(Buffer.from(part));
          }
        } finally { clearTimeout(timer); }
        const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
        if (Object.keys(body).join() !== "sourceId" || typeof body.sourceId !== "string"
          || !/^(all|SRC_\d{3})$/.test(body.sourceId)) throw new Error("source id");
        running = true;
        // Explicit POST only; consultation never starts provider calls. The Python
        // process enforces the persistent lock, immutable plan and remaining budget.
        void execute(body.sourceId).catch(() => undefined).finally(() => { running = false; });
        response.statusCode = 202;
        response.end(JSON.stringify({ status: "accepted", message: "Exécution demandée. Consultez les reçus pour son résultat." }));
      } else {
        reading ??= execute().then((r) => r.stdout).finally(() => { reading = undefined; });
        const result = JSON.parse(await reading);
        response.end(JSON.stringify({ ...result, running: result.running || running }));
      }
    } catch {
      response.statusCode = write ? 400 : 503;
      response.end(JSON.stringify({ status: "unavailable", message: "Collecte indisponible : vérifiez le plan local et les reçus." }));
    }
  }
  return { name: "robin-local-tipster-connectors", configResolved(config) { root = config.root; },
    configureServer(server) { server.middlewares.use(middleware); },
    configurePreviewServer(server) { server.middlewares.use(middleware); } };
}
