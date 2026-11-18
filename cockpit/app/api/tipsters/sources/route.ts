function localAccessRequired() {
  return Response.json({
    status: "unavailable",
    message: "Ouvrez Robin sur A9_Mega pour consulter et préparer les sources locales.",
  }, { status: 503, headers: { "Cache-Control": "no-store" } });
}

export const GET = localAccessRequired;
export const PUT = localAccessRequired;
