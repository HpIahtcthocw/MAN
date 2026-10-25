"""Stable record fingerprints, not signatures or proof of authorization.

Preserve the existing encoding exactly so extracting this module does not change
stored operation bindings, session hashes or the historical audit chain.
"""
import hashlib
import json


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()
