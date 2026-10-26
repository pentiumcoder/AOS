import os

import httpx
import pytest
from fastapi.testclient import TestClient
from harness import Api


@pytest.fixture
def api(request):
    services = request.config.getoption("--services")
    if services:
        with httpx.Client(
            base_url=os.environ.get("API_URL", "http://localhost:8000"), timeout=60
        ) as client:
            yield Api(client, services=True)
        return
    from aos.api.main import app

    with TestClient(app) as client:
        yield Api(client, services=False)
