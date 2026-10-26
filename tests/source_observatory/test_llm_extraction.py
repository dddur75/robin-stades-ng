"""Synthetic extraction contracts: no model, network or provider subprocess."""

import json
import sys
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from robin.source_observatory import models
from robin.source_observatory.schema_validation import validate_contribution
from robin.source_observatory.store import AppendOnlyStore

t = datetime(2026, 10, 26, tzinfo=UTC)
text = 'Mon pari : victoire de Reims cote 1,85'
prompt_sha256 = '69dafca29b2de56467427b0ff475bbcfaef27491d52a4c685304b2a8f567fe70'


def seeded(tmp_path, source_text=text):
    store = AppendOnlyStore(tmp_path / 'journal.jsonl')
    store.append_batch((
        models.Source('s', 'Synthetic', 'https://example.invalid'),
        models.Publication('p', 's', 'https://example.invalid/p'),
        models.PublicationVersion('v', 'p', models.text_fingerprint(source_text),
                                  None, t, None, t),
    ))
    return store


def pick(**changes):
    return dict(marche='1N2', selection='reims', ligne=None, cote_declaree='1.85',
                statut='resolu', raison_non_resolu=None) | changes


def response(*picks, **changes):
    return json.dumps(dict(id='v', contributions=list(picks), extrait_preuve=text) | changes)


def extract(store, source_text=text, output=None, **changes):
    from robin.source_observatory.llm_extraction import extract_contributions

    def route(request):
        assert json.loads(request.splitlines()[-1]) == {'id': 'v', 'texte': source_text}
        assert 'Tu es l\'EXTRACTEUR' in request
        return response(pick()) if output is None else output

    return extract_contributions(source_text, **(dict(
        store=store, version_id='v', author_id='a', observed_at=t, route=route,
    ) | changes))


def test_drafts_have_existing_lineage_and_prompt_journal(tmp_path):
    store = seeded(tmp_path)
    prefix = store.path.read_bytes()
    rows = extract(store)
    assert len(rows) == 1
    row = rows[0]
    validate_contribution(row)
    assert (row['publication_id'], row['version_id'], row['source_id']) == ('p', 'v', 's')
    assert row['text_sha256'] == sha256(text.encode()).hexdigest()
    assert row['cote_declaree'] == '1.85'
    assert (row['statut'], row['raison_non_resolu']) == ('non_resolu', 'match_non_rapproche')
    assert row['match_id'] is None
    assert row['extraits_preuve'][0]['text'] is None
    assert store.path.read_bytes().startswith(prefix)
    record = AppendOnlyStore(store.path).entities()[-1]
    assert record.prompt_sha256 == prompt_sha256
    assert record.drafts[0].extraction_metadata() | {'prompt_sha256': prompt_sha256} == row
    assert not any(isinstance(entity, models.Contribution) for entity in store.entities())
    assert text not in store.path.read_text(encoding='utf-8')


@pytest.mark.parametrize('invented', ['2.10', '11.85', '1.8', '1.850', '1e0'])
def test_nonliteral_odds_are_never_kept(tmp_path, invented):
    store = seeded(tmp_path)
    rows = extract(store, output=response(pick(cote_declaree=invented)))
    assert not rows or (rows[0]['cote_declaree'] is None
                        and rows[0]['raison_non_resolu'] == 'cote_non_litterale')
    assert all(draft.cote_declaree is None for draft in store.entities()[-1].drafts)


def test_changed_prompt_refuses_before_route_or_append(tmp_path):
    store = seeded(tmp_path)
    before = store.path.read_bytes()
    prompt = tmp_path / 'prompt.md'
    prompt.write_text('modified', encoding='utf-8')
    with pytest.raises(ValueError, match='prompt'):
        extract(store, prompt_path=prompt)
    assert store.path.read_bytes() == before


def test_noise_and_invalid_jsonl_lines_are_not_contributions(tmp_path):
    store = seeded(tmp_path)
    output = '\n'.join(('Here is the result:', '```jsonl', '{bad}', '[]',
                        response(pick(), id='wrong'), response(pick()), '```', 'Done.'))
    assert extract(store, output=output) == []
    record = store.entities()[-1]
    assert record.rejected_lines == 8
    assert record.prompt_sha256 == prompt_sha256


@pytest.mark.parametrize('changes', [
    {'marche': 'winner'}, {'selection': 'Reims'},
    {'marche': 'total', 'selection': 'more', 'ligne': '2.5'},
    {'marche': 'btts', 'selection': 'oui'},
    {'marche': 'double_chance', 'selection': '1X'},
    {'marche': 'score_exact', 'selection': '2:1'},
])
def test_invalid_canonical_vocabulary_remains_unresolved(tmp_path, changes):
    rows = extract(seeded(tmp_path), output=response(pick(**changes)))
    assert len(rows) == 1
    assert rows[0]['statut'] == 'non_resolu'
    assert rows[0]['raison_non_resolu'] == 'vocabulaire_non_canonique'
    assert rows[0]['cote_declaree'] is None


@pytest.mark.parametrize('source_text', ['', 'Le stade ouvre à 18 heures.',
                                         'Résultat : Reims 2-1 Metz.'])
def test_no_bet_cannot_be_hallucinated(tmp_path, source_text):
    store = seeded(tmp_path, source_text)
    assert extract(store, source_text,
                   output=response(pick(), extrait_preuve=source_text)) == []
    assert store.entities()[-1].drafts == ()
    assert store.entities()[-1].prompt_sha256 == prompt_sha256


@pytest.mark.parametrize('output', [
    response(pick(ligne=[])), response(pick(cote_declaree=True)),
    response(pick(secret='do not persist')), response(pick(), payload='do not persist'),
    '{"id":"v","id":"v","contributions":[],"extrait_preuve":""}',
    response(pick(cote_declaree=float('nan'))),
])
def test_invalid_shapes_are_rejected_without_raw_output(tmp_path, output):
    store = seeded(tmp_path)
    assert extract(store, output=output) == []
    assert store.entities()[-1].rejected_lines == 1
    assert 'do not persist' not in store.path.read_text(encoding='utf-8')


def test_unknown_version_and_wrong_text_refuse_before_route(tmp_path):
    store = seeded(tmp_path)
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match='version'):
        extract(store, version_id='missing')
    with pytest.raises(ValueError, match='sha256'):
        extract(store, source_text=text + '!')
    assert store.path.read_bytes() == before


def test_excerpt_must_be_literal_and_bounded(tmp_path):
    source_text = text + ' ' + 'synthetic ' * 100
    store = seeded(tmp_path, source_text)
    row = extract(store, source_text, output=response(pick(), extrait_preuve=text),
                  preuve_permise='https://example.invalid/permission')[0]
    excerpt = row['extraits_preuve'][0]
    assert excerpt['text'] == text
    assert source_text[excerpt['start']:excerpt['end']] == excerpt['text']
    validate_contribution(row)


def test_invented_excerpt_is_rejected(tmp_path):
    assert extract(seeded(tmp_path), output=response(pick(), extrait_preuve='invented')) == []


def test_adapter_runs_local_child_with_stdin_and_no_shell(tmp_path, monkeypatch):
    from robin.source_observatory.llm_extraction import AgyRoute

    # A local Python echo child exercises transport without any agy/model/network.
    monkeypatch.setenv('ROBIN_AGY_COMMAND', json.dumps([
        sys.executable, '-c', 'import sys; print(sys.stdin.read(), end="")',
    ]))
    assert AgyRoute.from_env()('synthetic request') == 'synthetic request'


def test_adapter_failure_does_not_leak_child_diagnostics(monkeypatch):
    from robin.source_observatory.llm_extraction import AgyRoute

    monkeypatch.setenv('ROBIN_AGY_COMMAND', json.dumps([
        sys.executable, '-c', 'import sys; print("private", file=sys.stderr); sys.exit(1)',
    ]))
    with pytest.raises(RuntimeError, match='agy') as exc:
        AgyRoute.from_env()('synthetic')
    assert 'private' not in str(exc.value)


@pytest.mark.parametrize('command', ['not json', '[]', '"agy"', '["agy", 1]'])
def test_adapter_invalid_configuration_never_launches(monkeypatch, command):
    from robin.source_observatory.llm_extraction import AgyRoute

    monkeypatch.setenv('ROBIN_AGY_COMMAND', command)
    with pytest.raises(ValueError, match='ROBIN_AGY_COMMAND'):
        AgyRoute.from_env()


@pytest.mark.parametrize('source_text', [
    'Mon pari : victoire de Reims cote 11.85',
    'Mon pari : victoire de Reims cote 1.850',
    'Mon pari : victoire de Reims cote 1.85e2',
    'Mon pari : victoire de Reims cote x1.85',
])
def test_odds_cannot_match_part_of_another_token(tmp_path, source_text):
    store = seeded(tmp_path, source_text)
    row = extract(store, source_text,
                  output=response(pick(), extrait_preuve=source_text))[0]
    assert row['cote_declaree'] is None
    assert row['raison_non_resolu'] == 'cote_non_litterale'


def test_one_bad_contribution_rejects_the_entire_jsonl_line(tmp_path):
    store = seeded(tmp_path)
    assert extract(store, output=response(pick(), pick(ligne=[]))) == []
    assert store.entities()[-1].rejected_lines == 1


def test_absent_odds_stay_absent(tmp_path):
    source_text = 'Mon pari : victoire de Reims'
    store = seeded(tmp_path, source_text)
    row = extract(store, source_text, output=response(
        pick(cote_declaree=None), extrait_preuve=source_text))[0]
    assert row['cote_declaree'] is None
    assert row['cote_declaree_at'] is None
    assert row['cote_declaree_provenance'] is None
    assert row['categorie'] == 'selection_sans_cote'


@pytest.mark.parametrize('source_text,changes', [
    ('Mon pari : over 2,5 buts cote 1,85',
     {'marche': 'total', 'selection': 'over', 'ligne': '2.5'}),
    ('Mon pari : les deux équipes marquent cote 1,85',
     {'marche': 'btts', 'selection': 'yes'}),
    ('Mon pari : double chance 1N cote 1,85',
     {'marche': 'double_chance', 'selection': 'home_or_draw'}),
])
def test_canonical_markets_keep_literal_odds_but_not_resolved_match(tmp_path, source_text,
                                                                 changes):
    store = seeded(tmp_path, source_text)
    row = extract(store, source_text,
                  output=response(pick(**changes), extrait_preuve=source_text))[0]
    assert row['cote_declaree'] == '1.85'
    assert row['raison_non_resolu'] == 'match_non_rapproche'
    assert row['match_id'] is None


def test_no_bet_invokes_route_and_journals_empty_response(tmp_path):
    from robin.source_observatory.llm_extraction import extract_contributions

    source_text = 'Le stade ouvre à 18 heures.'
    store = seeded(tmp_path, source_text)

    requests = []

    def route(request):
        requests.append(json.loads(request.splitlines()[-1]))
        return response(extrait_preuve='')

    assert extract_contributions(source_text, store=store, version_id='v', author_id='a',
                                 observed_at=t, route=route) == []
    assert requests == [{'id': 'v', 'texte': source_text}]
    assert store.entities()[-1].drafts == ()


def test_missing_frozen_digest_refuses_before_any_append(tmp_path):
    store = seeded(tmp_path)
    before = store.path.read_bytes()
    freeze = tmp_path / 'freeze.md'
    freeze.write_text('sha256: missing', encoding='utf-8')
    with pytest.raises(ValueError, match='prompt'):
        extract(store, freeze_path=freeze)
    assert store.path.read_bytes() == before


def test_adapter_timeout_is_sanitized(monkeypatch):
    from robin.source_observatory.llm_extraction import AgyRoute

    route = AgyRoute((sys.executable, '-c', 'import time; time.sleep(2)'), timeout=0.05)
    with pytest.raises(RuntimeError, match='agy transport failed'):
        route('private synthetic request')


def test_explicit_refusal_to_bet_cannot_become_a_contribution(tmp_path):
    source_text = 'Je ne joue pas la victoire de Reims cote 1,85.'
    store = seeded(tmp_path, source_text)
    assert extract(store, source_text,
                   output=response(pick(), extrait_preuve=source_text)) == []
