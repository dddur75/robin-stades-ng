import { execFile } from "node:child_process";
import { resolve } from "node:path";
import { promisify } from "node:util";
import type { Plugin } from "vite";
import type { IncomingMessage, ServerResponse } from "node:http";
import { permitsLocalPilotRead } from "./tipsters-pilot-plugin";

const runFile = promisify(execFile);

export function publicTipsters(): Plugin {
  let root = process.cwd();
  let pending: Promise<string> | undefined;
  const middleware = async (request: IncomingMessage, response: ServerResponse, next: () => void) => {
    if (request.url?.split("?")[0] !== "/api/tipsters/public") return next();
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("Content-Type", "application/json; charset=utf-8");
    response.setHeader("X-Content-Type-Options", "nosniff");
    if (!permitsLocalPilotRead(request)) {
      response.statusCode = 403; response.end(JSON.stringify({status:"forbidden",message:"Accès local A9_Mega requis."})); return;
    }
    try {
      const repository = resolve(root, "..");
      const python = process.env.ROBIN_TIPSTERS_PYTHON ?? resolve(repository, ".venv",process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
      pending ??= runFile(python, ["-X","utf8","-B",resolve(root,"scripts/read-public-tipsters.py"),
        "--directory",process.env.ROBIN_PUBLIC_TIPSTERS_DIRECTORY ?? resolve(root,".ci/tipsters-unblock-20261119")],
      {timeout:8000,maxBuffer:12000000,windowsHide:true,encoding:"utf8"}).then(r=>r.stdout).finally(()=>{pending=undefined;});
      const result = await pending;
      if (JSON.parse(result).status !== "ok") response.statusCode=503;
      response.end(result);
    } catch {
      response.statusCode=503;response.end(JSON.stringify({status:"unavailable",message:"La lecture des preuves publiques a échoué."}));
    }
  };
  return {name:"robin-local-public-tipsters",configResolved(config){root=config.root;},
    configureServer(server){server.middlewares.use(middleware);},configurePreviewServer(server){server.middlewares.use(middleware);}};
}
