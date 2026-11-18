import assert from "node:assert/strict";
import type { IncomingMessage } from "node:http";
import test from "node:test";

import { permitsLocalPilotAccess, permitsLocalPilotRead } from "../scripts/tipsters-pilot-plugin";

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

test("la collecte explicite requiert POST JSON local de même origine", () => {
  const headers = { origin: "http://127.0.0.1:4173", "content-type": "application/json" };
  assert.equal(permitsLocalPilotAccess(request({ method: "POST", headers }), "POST"), true);
  assert.equal(permitsLocalPilotAccess(request({ method: "POST" }), "POST"), false);
  assert.equal(permitsLocalPilotAccess(request({ method: "GET", headers }), "POST"), false);
  assert.equal(permitsLocalPilotAccess(request({ method: "POST", headers, address: "192.168.0.2" }), "POST"), false);
});

test("la sauvegarde requiert PUT, JSON et une origine exacte", () => {
  const valid = { method: "PUT", headers: { origin: "http://127.0.0.1:4173", "content-type": "application/json" } };
  assert.equal(permitsLocalPilotAccess(request(valid), "PUT"), true);
  assert.equal(permitsLocalPilotAccess(request({ method: "PUT" }), "PUT"), false);
  assert.equal(permitsLocalPilotAccess(request({ ...valid, headers: { ...valid.headers, origin: "http://127.0.0.1:4174" } }), "PUT"), false);
  assert.equal(permitsLocalPilotAccess(request({ ...valid, headers: { ...valid.headers, "content-type": "text/plain" } }), "PUT"), false);
  assert.equal(permitsLocalPilotAccess(request({ ...valid, address: "192.168.1.2" }), "PUT"), false);
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
