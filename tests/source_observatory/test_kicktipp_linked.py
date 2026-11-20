import pytest

from robin.source_observatory.kicktipp_linked import project_linked_overview

URL = "https://www.kicktipp.fr/the-predictor/tableau-pronostics"


def document(game="123", header_game="123", cell="2:1", author=True):
    person = (
        '<a href="/the-predictor/tippuebersicht/tipper?rankingTeilnehmerId=9">Alice</a>'
        if author
        else "Alice"
    )
    return f"""<table id="spielplanSpiele"><tr><th>Date</th><th>À domicile</th><th>A l'extérieur</th><th>Résultat</th></tr><tr><td>21.11.2026 15:00</td><td><a href="/the-predictor/spielinfo?spielIndex={game}">Liverpool</a></td><td>Manchester United</td><td>-:-</td></tr></table><table id="ranking"><tr><th>Pos.</th><th>Nom</th><th><a href="/the-predictor/spielinfo?spielIndex={header_game}">LIV MUN - - -</a></th><th>P</th></tr><tr><th>1</th><td>{person}</td><td>{cell}</td><td>8</td></tr></table>""".encode()


def test_native_game_reference_binds_abbreviation_without_guessing_teams():
    value = project_linked_overview(document(), "text/html", URL)
    cell = value["participants"][0]["cells"][0]
    assert cell["nativeSelection"] == "2:1"
    assert cell["nativeHome"] == "Liverpool" and cell["nativeAway"] == "Manchester United"
    assert value["participants"][0]["nativeAuthorRef"].endswith("rankingTeilnehmerId=9")
    assert cell["sourceTimezone"] is None and value["admittedChoices"] == 0


@pytest.mark.parametrize("body", [document(header_game="999"), document(cell="-:-")])
def test_missing_binding_or_masked_score_never_becomes_personal_choice(body):
    value = project_linked_overview(body, "text/html", URL)
    assert not value["participants"] and value["admittedChoices"] == 0


def test_pseudonym_without_native_author_reference_is_explicitly_unattributed():
    value = project_linked_overview(document(author=False), "text/html", URL)
    assert value["participants"][0]["nativeAuthorRef"] is None
    assert value["admittedChoices"] == 0


def test_title_only_challenge_stops_even_when_body_has_a_valid_table():
    with pytest.raises(ValueError, match="challenge"):
        project_linked_overview(
            b"<head><title>Just a moment</title></head>" + document(), "text/html", URL
        )


def test_new_header_cannot_reuse_previous_native_column_bindings():
    header = b"<tr><th>Pos.</th><th>Nom</th><th>No native game link</th><th>P</th></tr>"
    body = document().replace(b"<tr><th>1</th>", header + b"<tr><th>1</th>")
    assert not project_linked_overview(body, "text/html", URL)["participants"]


def test_participant_named_nom_in_td_is_not_a_header():
    body = document(author=False).replace(b"<td>Alice</td>", b"<td>Nom</td>")
    assert project_linked_overview(body, "text/html", URL)["participants"][0]["pseudonym"] == "Nom"


def test_bounded_projection_prefers_unresolved_source_result_without_claiming_future():
    schedule = "".join(
        f'<tr><td>21.11.2026 15:00</td><td><a href="/the-predictor/spielinfo?spielIndex={i}">Home{i}</a></td><td>Away{i}</td><td>{"-:-" if i == 4 else "1:0"}</td></tr>'
        for i in range(1, 5)
    )
    headers = "".join(
        f'<th><a href="/the-predictor/spielinfo?spielIndex={i}">H{i} A{i}</a></th>'
        for i in range(1, 5)
    )
    body = f'<table id="spielplanSpiele"><tr><th>Date</th><th>À domicile</th><th>A l\'extérieur</th><th>Résultat</th></tr>{schedule}</table><table id="ranking"><tr><th>Nom</th>{headers}</tr><tr><td>Alice</td><td>1:0</td><td>1:0</td><td>1:0</td><td>2:1</td></tr></table>'.encode()
    value = project_linked_overview(body, "text/html", URL)
    assert value["participants"][0]["cells"][0]["nativeHome"] == "Home4"
    assert len(value["participants"][0]["cells"]) == 3
    assert value["canonicalKickoffsEstablished"] is False and value["admittedChoices"] == 0
