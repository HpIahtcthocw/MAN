"""Cross-adapter precision and stored-binding compatibility regression cases."""
import hashlib
import json

import pytest

from guardian.core import digest, parse_major_units
from guardian.engine import money, Denied


def test_same_provider_amount_has_precision_explicitly_selected():
    # These are configured precisions, not a built-in currency database.
    assert parse_major_units('100', exponent=0) == 100
    assert parse_major_units('100', exponent=2) == 10000
    assert parse_major_units('100.125', exponent=3) == 100125
    assert money('100') == 10000
    with pytest.raises(Denied):
        money('100.125')


@pytest.mark.parametrize('text,precision', [('1.01', 0), ('1.001', 2),
    ('1e2', 2), ('+1', 2), ('NaN', 2), (' 1', 2), ('1,000', 2), (1.0, 2)])
def test_provider_inputs_cannot_silently_round_or_change_units(text, precision):
    with pytest.raises(ValueError):
        parse_major_units(text, exponent=precision)


def test_existing_operation_and_audit_encoding_does_not_change():
    record = {'owner': 'demo', 'kind': 'transfer',
              'payload': {'amount_cents': 10000, 'note': '房租'}}
    previous_encoding = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    assert digest(record) == hashlib.sha256(previous_encoding.encode()).hexdigest()
    changed = {**record, 'payload': {**record['payload'], 'amount_cents': 10001}}
    assert digest(changed) != digest(record)
