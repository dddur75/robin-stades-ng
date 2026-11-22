import { open } from "node:fs/promises";
import { resolve } from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";
import { parseQualificationSnapshot, type QualificationSnapshot } from "../app/lib/tipster-qualification";
import { permitsLocalPilotRead } from "./tipsters-pilot-plugin";

const maximumBytes = 131_072;

export async function readQualificationSnapshot(path: string): Promise<QualificationSnapshot> {
  const file = await open(path, "r");
  try {
    const stat = await file.stat();
    if (!stat.isFile() || stat.size > maximumBytes) throw new Error("Invalid snapshot size");
    const buffer = Buffer.alloc(maximumBytes + 1);
    let size = 0;
    while (size < buffer.length) {
      const { bytesRead } = await file.read(buffer, size, buffer.length - size, null);
      if (!bytesRead) break;
      size += bytesRead;
    }
    if (size > maximumBytes) throw new Error("Invalid snapshot size");
    return parseQualificationSnapshot(JSON.parse(buffer.toString("utf8", 0, size)));
  } finally { await file.close(); }
}

export function qualificationMiddleware(read: () => Promise<QualificationSnapshot>) {
  return async (request: IncomingMessage, response: ServerResponse, next: () => void) => {
    if (request.url?.split("?")[0] !== "/api/tipsters/qualification") return next();
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("Content-Type", "application/json; charset=utf-8");
    response.setHeader("X-Content-Type-Options", "nosniff");
    if (!permitsLocalPilotRead(request)) {
      response.statusCode = 403;
      response.end(JSON.stringify({ status: "forbidden", message: "Accès local A9_Mega requis." }));
      return;
    }
    try { response.end(JSON.stringify({ status: "ok", ...await read() })); }
    catch {
      response.statusCode = 503;
      response.end(JSON.stringify({ status: "unavailable", message: "Les preuves de qualification sont indisponibles." }));
    }
  };
}

export function tipsterQualification(): Plugin {
  let root = process.cwd();
  const middleware = qualificationMiddleware(() => readQualificationSnapshot(resolve(root, ".ci/local-robin/source-qualification.json")));
  return { name: "robin-local-source-qualification", configResolved(config) { root = config.root; },
    configureServer(server) { server.middlewares.use(middleware); },
    configurePreviewServer(server) { server.middlewares.use(middleware); } };
}
