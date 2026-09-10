import pytest


@pytest.fixture(autouse=True)
def _reset_adapters():
    from integrations.registry import reset_adapter_cache

    reset_adapter_cache()
    yield
    reset_adapter_cache()
