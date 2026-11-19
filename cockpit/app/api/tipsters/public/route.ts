export function GET() {
  return Response.json({ status: "unavailable", message: "Ouvrez Robin sur A9_Mega pour consulter la collecte publique locale." },
    { status: 503, headers: { "Cache-Control": "no-store" } });
}
