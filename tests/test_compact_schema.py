"""The compact prompt schema must stay in sync with the pydantic Plan model."""
from guardian.task_planner import BillQuery, Choice, Plan, compact_schema, prompt


def test_every_field_name_and_enum_survives_compaction():
    text = compact_schema()
    for field in Plan.model_fields:
        if field != 'nodes':  # nodes is host-owned and deliberately absent from semantic_schema too
            assert field in text, field
    for field in BillQuery.model_fields:
        assert field in text, field
    for field in Choice.model_fields:
        assert field in text, field
    for group in ('transfer', 'subscriptions', 'bills', 'safety_info', 'clarify', 'unsupported',
                  'update', 'pause', 'resume', 'handoff', 'using', 'unneeded', 'unknown'):
        assert group in text, group
    assert 'YYYY-MM-DD' in text and 'false' in text


def test_prompt_uses_compact_schema_and_stays_small():
    context = {'kind': 'transfer', 'draft': {}, 'bill_query': None, 'contacts': [], 'turns': [], 'subscriptions': []}
    text = prompt(context)
    assert compact_schema() in text
    assert 'json.dumps' not in text and '"anyOf"' not in text and '"$defs"' not in text
    # The old full JSON-Schema serialization was ~2900 chars; keep the whole
    # system instruction well below the previous 4223-char total.
    assert len(text) < 2600, len(text)
