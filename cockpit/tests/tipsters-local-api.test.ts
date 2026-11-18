import assert from "node:assert/strict";
import type { IncomingMessage } from "node:http";
import test from "node:test";

import { permitsLocalPilotRead } from "../scripts/tipsters-pilot-plugin";

function request(overrides: { method?: string; address?: string; headers?: Record<string, string> } = {}) {
  return {
    method: overrides.method ?? "GET", socket: { remoteAddress: overrides.address ?? "127.0.0.1" },
    headers: { host: "127.0.0.1:4173", ...overrides.headers },
  } as unknown as IncomingMessage;
}

test("le suivi autorise une lecture locale de même origine", () => {
  assert.equal(permitsLocalPilotRead(request()), true);
  assert.equal(permitsLocalPilotRead(request({ headers: { origin: "http://127.0.0.1:4173", "sec-fetch-site": "same-origin" } })), true);
});

test("le suivi refuse les autres méthodes, origines, ports, hôtes et clients réseau", () => {
  for (const denied of [
    request({ method: "POST" }), request({ address: "192.168.1.2" }),
    request({ headers: { host: "example.invalid:4173" } }),
    request({ headers: { origin: "https://example.invalid" } }),
    request({ headers: { origin: "http://127.0.0.1:4174" } }),
    request({ headers: { "sec-fetch-site": "cross-site" } }),
    request({ headers: { host: "127.0.0.1:4173@external.invalid" } }),
    request({ headers: { host: "127.0.0.1:4173/evil" } }),
  ]) assert.equal(permitsLocalPilotRead(denied), false);
});
