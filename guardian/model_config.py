"""Operator-only local configuration; never returned to the browser or logged."""
import json
import os
from pathlib import Path

CONFIG_FILE = Path(__file__).absolute().parent.parent / 'data' / 'model.local.json'


def settings():
    local = {}
    if CONFIG_FILE.is_file():
        try:
            local = json.loads(CONFIG_FILE.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            return {}
    if not isinstance(local, dict): return {}
    result = {}
    for key in ('base_url', 'api_key', 'model'):
        value = os.getenv('GUARDIAN_LLM_' + key.upper()) or local.get(key, '')
        result[key] = value.strip() if isinstance(value, str) else ''
    return result
