import pytest


@pytest.fixture(autouse=True)
def llm_router_key(settings):
    """Tests mock the model call; the router still refuses to build without a key (CI has none)."""
    settings.LLM_API_KEY = "test-key"
