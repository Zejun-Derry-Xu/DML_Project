"""Static exposure contracts; these checks never start Docker or a model."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def service_block(name: str) -> str:
    source = (ROOT / "compose.jetstream.yml").read_text()
    match = re.search(rf"^  {name}:\n(.*?)(?=^  \w+:|^volumes:|\Z)", source, re.M | re.S)
    assert match is not None
    return match.group(1)


def test_public_demo_requires_explicit_frontend_opt_in():
    assert '"${FRONTEND_BIND_ADDRESS:-127.0.0.1}:5173:80"' in service_block("frontend")
    example = (ROOT / ".env.jetstream.example").read_text()
    assert "FRONTEND_BIND_ADDRESS=127.0.0.1" in example.splitlines()
    assert "FRONTEND_BIND_ADDRESS=0.0.0.0" not in example.splitlines()


def test_api_stays_loopback_and_data_and_model_have_no_host_port():
    assert '"127.0.0.1:8000:8000"' in service_block("api")
    for name in ("db", "ollama"):
        assert re.search(r"^    ports:", service_block(name), re.M) is None


def test_dashscope_key_is_private_to_the_api_service():
    api = service_block("api")
    assert "DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY:-}" in api
    assert "LLM_PROVIDER: ${LLM_PROVIDER:-ollama}" in api
    assert "DASHSCOPE" not in service_block("frontend")
    assert "DASHSCOPE" not in service_block("db")
    assert "sk-" not in (ROOT / "compose.jetstream.yml").read_text()
    assert 'profiles: ["model"]' in service_block("ollama")


def test_public_frontend_keeps_same_origin_api_proxy():
    nginx = (ROOT / "frontend/nginx/default.conf").read_text()
    assert "proxy_pass http://api:8000;" in nginx
    assert 'add_header Cache-Control "no-store" always;' in nginx
