from datetime import UTC, datetime

import pytest

from robin.source_observatory.candidate_forums import extract_sro_posts, qualify_sro_posts

URL = "https://forum.stade-rennais-online.com/viewtopic.php?id=6368"
NOW = datetime(2026, 11, 19, 14, tzinfo=UTC)
FIX = [
    dict(
        id="j11-troyes-havre",
        label="Troyes – Le Havre",
        kickoff="2026-11-20T19:45:00Z",
        publicationWindowStart="2026-11-09",
        homeAliases=["Troyes", "ESTAC Troyes"],
        awayAliases=["Le Havre", "Havre AC"],
    )
]


def html(text="20:45 ESTAC Troyes 3 - 1 Havre AC", author="Nomade", date="15-11-2026 18:45:20"):
    return f'<div id="p42" class="blockpost"><h2>#{date}</h2><div class="postleft"><dl><dt><a href="profile.php?id=15388">{author}</a></dt></dl></div><div class="postmsg"><p>{text}</p></div><div class="postsignature postmsg">ESTAC Troyes 9 - 9 Havre AC</div></div>'.encode()


def picks(body=None, now=NOW):
    return qualify_sro_posts(extract_sro_posts(body or html(), URL, now), FIX)


def test_personal_prematch_choice_profile_and_provenance():
    rows = picks()
    assert len(rows) == 1
    assert rows[0]["selection"] == "3-1" and rows[0]["sourceId"] == "SRC_039"
    assert rows[0]["authorUrl"] == "https://forum.stade-rennais-online.com/profile.php?id=15388"
    assert rows[0]["publishedCivilDate"] == "2026-11-15" and rows[0]["identityCertified"] is False
    assert rows[0]["responseSha256"]


@pytest.mark.parametrize(
    "text",
    [
        "<blockquote>ESTAC Troyes 3 - 1 Havre AC</blockquote>",
        "ESTAC Troyes - Havre AC",
        "Un autre match 3 - 1",
        "Si je devais choisir ESTAC Troyes 3 - 1 Havre AC",
        "ESTAC Troyes 3 - 1 Havre AC cote 9.0",
    ],
)
def test_no_quotes_schedule_guess_unmatched_or_extra_suffix(text):
    assert picks(html(text)) == []


def test_postkickoff_and_old_or_future_publication_refused():
    assert picks(now=datetime(2026, 11, 20, 19, 45, tzinfo=UTC)) == []
    assert picks(html(date="01-10-2026 18:45:20")) == []
    assert picks(html(date="20-11-2026 18:45:20")) == []


def test_guest_and_conflicting_same_fixture_refused():
    assert picks(html(author="Invité")) == []
    assert picks(html("ESTAC Troyes 3 - 1 Havre AC<br>ESTAC Troyes 0 - 0 Havre AC")) == []


def test_scope_and_timezone_fail_closed():
    with pytest.raises(ValueError):
        extract_sro_posts(html(), URL.replace("6368", "6365"), NOW)
    with pytest.raises(ValueError):
        extract_sro_posts(html(), URL, NOW.replace(tzinfo=None))


def test_new_message_from_same_author_revises_same_prediction_id():
    first = picks()[0]
    second = picks(html("ESTAC Troyes 0 - 0 Havre AC").replace(b"p42", b"p43"))[0]
    assert first["id"] == second["id"]


def test_latest_authored_message_wins_without_double_counting():
    body = html() + html("ESTAC Troyes 0 - 0 Havre AC", date="16-11-2026 18:45:20").replace(
        b"p42", b"p43"
    )
    rows = picks(body)
    assert len(rows) == 1 and rows[0]["selection"] == "0-0"


@pytest.mark.parametrize(
    "text",
    [
        "Ce ne sont pas mes pronostics<br>ESTAC Troyes 3 - 1 Havre AC",
        "Grille de Paul<br>ESTAC Troyes 3 - 1 Havre AC",
        "Voici mon dernier match de coupe<br>ESTAC Troyes 3 - 1 Havre AC",
        "<template>ESTAC Troyes 3 - 1 Havre AC</template>",
        "<del>ESTAC Troyes 3 - 1 Havre AC</del>",
        "Les pronostics de Pierre<br>ESTAC Troyes 3 - 1 Havre AC",
    ],
)
def test_reviewer_rejection_attribution_and_hidden_cases(text):
    assert picks(html(text)) == []
