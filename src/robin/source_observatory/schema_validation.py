"""Validation of the bundled schema, including a dependency-free fallback.

The fallback implements the keywords used by contribution.schema.json and
rejects unknown validation keywords rather than silently weakening the contract.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def _fallback(value: Any, rule: dict[str, Any], root: dict[str, Any]) -> None:
    supported = {
        '$schema', '$id', '$defs', '$ref', 'title', 'description', 'type',
        'additionalProperties', 'required', 'properties', 'pattern', 'format',
        'minLength', 'maxLength', 'minimum', 'exclusiveMinimum', 'exclusiveMaximum',
        'enum', 'const', 'items', 'maxItems', 'contains', 'minContains', 'maxContains',
        'allOf', 'anyOf', 'if', 'then', 'else',
    }
    if rule.keys() - supported:
        raise ValueError('unsupported schema keyword')
    if '$ref' in rule:
        target = root
        for part in rule['$ref'].removeprefix('#/').split('/'):
            target = target[part]
        _fallback(value, target, root)

    def matches(subrule: dict[str, Any]) -> bool:
        try:
            _fallback(value, subrule, root)
            return True
        except ValueError:
            return False

    kinds = {
        'null': value is None, 'string': isinstance(value, str),
        'integer': type(value) is int,
        'object': isinstance(value, dict), 'array': isinstance(value, list),
    }
    types = rule.get('type', list(kinds))
    if isinstance(types, str):
        types = [types]
    if not any(kinds.get(kind, False) for kind in types):
        raise ValueError('schema type mismatch')
    if 'const' in rule and value != rule['const']:
        raise ValueError('schema const mismatch')
    if 'enum' in rule and value not in rule['enum']:
        raise ValueError('schema enum mismatch')
    if isinstance(value, dict):
        if set(rule.get('required', [])) - value.keys():
            raise ValueError('schema required property absent')
        properties = rule.get('properties', {})
        if rule.get('additionalProperties') is False and value.keys() - properties.keys():
            raise ValueError('schema additional property')
        for key in value.keys() & properties.keys():
            _fallback(value[key], properties[key], root)
    if isinstance(value, str):
        if not rule.get('minLength', 0) <= len(value) <= rule.get('maxLength', float('inf')):
            raise ValueError('schema string length')
        if 'pattern' in rule and not re.search(rule['pattern'], value):
            raise ValueError('schema string pattern')
        if rule.get('format') == 'uri':
            if not urlsplit(value).scheme or re.search(r'\s', value):
                raise ValueError('schema uri format')
        if rule.get('format') == 'date-time':
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError('schema date-time format') from exc
            if parsed.tzinfo is None or not re.fullmatch(
                    r'\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})',
                    value):
                raise ValueError('schema date-time timezone')
    if type(value) in (int, float):
        if value < rule.get('minimum', -float('inf')):
            raise ValueError('schema minimum')
        if value <= rule.get('exclusiveMinimum', -float('inf')):
            raise ValueError('schema exclusive minimum')
        if value >= rule.get('exclusiveMaximum', float('inf')):
            raise ValueError('schema exclusive maximum')
    if isinstance(value, list):
        if len(value) > rule.get('maxItems', float('inf')):
            raise ValueError('schema maxItems')
        for item in value:
            _fallback(item, rule.get('items', {}), root)
        if 'contains' in rule:
            count = 0
            for item in value:
                try:
                    _fallback(item, rule['contains'], root)
                    count += 1
                except ValueError:
                    pass
            if not rule.get('minContains', 1) <= count <= rule.get('maxContains', float('inf')):
                raise ValueError('schema contains')
    for child in rule.get('allOf', []):
        _fallback(value, child, root)
    if 'anyOf' in rule and not any(matches(child) for child in rule['anyOf']):
        raise ValueError('schema anyOf')
    if 'if' in rule:
        branch = 'then' if matches(rule['if']) else 'else'
        _fallback(value, rule.get(branch, {}), root)


def validate_contribution(contribution: dict[str, Any]) -> None:
    """Raise ValueError on a schema violation; never disable validation."""
    schema = json.loads((Path(__file__).parent / 'schemas' / 'contribution.schema.json')
                        .read_text(encoding='utf-8'))
    try:
        from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
    except ImportError:
        _fallback(contribution, schema, schema)
        return
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker())
                  .iter_errors(contribution))
    if errors:
        raise ValueError('contribution schema violation: ' + errors[0].message)
