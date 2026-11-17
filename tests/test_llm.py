"""LLM client: allow-list, fallback chain and provider error handling. Uses a mock HTTP transport."""
import json

import httpx
import pytest

import config
import llm

GOOD_OLLAMA = {"message": {"content": json.dumps({"speech": "ok"})}, "prompt_eval_count": 10, "eval_count": 5}


def client_with(monkeypatch, tmp_path, handler, key="sk-hc-v1-testkeyplaceholder"):
    monkeypatch.setenv("LLM_API_KEY", key)
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    return llm.LLMClient(http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_extract_json_tolerates_fences_and_think_blocks():
    assert llm.extract_json('<think>hmm</think>```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.extract_json('Sure! {"a": {"b": 2}} done') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        llm.extract_json("no json here")


def test_closed_models_are_blocked_and_unknown_models_refused():
    assert config.is_blocked("qwen/qwen4-max") and config.is_blocked("z-ai/glm-5.1")
    assert config.is_blocked("anthropic/claude-x") and config.is_blocked("openai/gpt-5")
    assert not config.is_blocked("z-ai/glm-5.3")
    assert "some/closed-model" not in config.allowed_models("hackclub")


def test_no_key_means_local_ollama_only(monkeypatch, tmp_path):
    client = client_with(monkeypatch, tmp_path, lambda r: httpx.Response(200, json=GOOD_OLLAMA), key="")
    assert client.cfg["chain"] == ["ollama"]
    result = client.chat_json("researcher", "s", "u")
    assert result.provider == "ollama" and result.cost == 0 and result.model == "qwen3:8b"


def test_402_falls_back_to_local_and_notifies(monkeypatch, tmp_path):
    notices = []

    def handler(request):
        if "hackclub" in request.url.host:
            return httpx.Response(200, json={"data": []}) if request.url.path.endswith("/models") else httpx.Response(402)
        return httpx.Response(200, json=GOOD_OLLAMA)

    client = client_with(monkeypatch, tmp_path, handler)
    client.notify = lambda level, message: notices.append(message)
    assert client.chat_json("researcher", "s", "u").provider == "ollama"
    assert any("402" in n for n in notices)


def test_403_stops_and_is_not_retried(monkeypatch, tmp_path):
    hits = []

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        hits.append(request.url.host)
        return httpx.Response(403)

    client = client_with(monkeypatch, tmp_path, handler)
    with pytest.raises(llm.ProviderForbidden):
        client.chat_json("researcher", "s", "u")
    assert hits == ["ai.hackclub.com"]


def test_429_honours_retry_after_then_succeeds(monkeypatch, tmp_path):
    state = {"n": 0}
    body = {"choices": [{"message": {"content": '{"speech": "ok"}'}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 1000}}

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "z-ai/glm-5.3-flash", "hugging_face_id": "zai-org/GLM-5.3-Flash",
                                                       "pricing": {"prompt": "0.00000015", "completion": "0.0000005"}}]})
        state["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "1"}) if state["n"] == 1 else httpx.Response(200, json=body)

    client = client_with(monkeypatch, tmp_path, handler)
    result = client.chat_json("researcher", "s", "u")
    assert result.provider == "hackclub" and state["n"] == 2
    assert result.cost == pytest.approx(0.00065)             # 1000 * $0.15/M + 1000 * $0.50/M
    assert client.budget.spent() == pytest.approx(0.00065)


def test_catalog_entry_without_open_weights_is_refused(monkeypatch, tmp_path):
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "z-ai/glm-5.3-flash", "hugging_face_id": ""}]})
        if "hackclub" in request.url.host:
            raise AssertionError("a model without open weights must never be called")
        return httpx.Response(200, json=GOOD_OLLAMA)

    client = client_with(monkeypatch, tmp_path, handler)
    assert client.chat_json("researcher", "s", "u").provider == "ollama"


def test_budget_cap_stops_metered_spend(monkeypatch, tmp_path):
    monkeypatch.setenv("DAILY_BUDGET_USD", "0")

    def handler(request):
        if "hackclub" in request.url.host and not request.url.path.endswith("/models"):
            raise AssertionError("over budget: the metered provider must not be called")
        return httpx.Response(200, json={"data": []} if "hackclub" in request.url.host else GOOD_OLLAMA)

    client = client_with(monkeypatch, tmp_path, handler)
    assert client.chat_json("researcher", "s", "u").provider == "ollama"
