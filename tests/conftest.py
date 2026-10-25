"""Unit tests never load operator credentials or make paid model requests."""
import pytest


@pytest.fixture(autouse=True)
def isolate_model_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr('guardian.model_config.CONFIG_FILE', tmp_path / 'no-model-config.json')
    for name in ('GUARDIAN_LLM_BASE_URL', 'GUARDIAN_LLM_API_KEY', 'GUARDIAN_LLM_MODEL'):
        monkeypatch.delenv(name, raising=False)
