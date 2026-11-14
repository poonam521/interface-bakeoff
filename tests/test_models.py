from types import SimpleNamespace

import anthropic
import httpx2 as httpx  # the HTTP library the installed Anthropic SDK (2.x) is built on
import pytest

from bakeoff.models import (PRICES, AnthropicModel, FatalModelError, Part, cost_usd, estimate_input_tokens,
                            worst_case_usd)
from bakeoff.types import Usage


class StubMessages:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.kwargs = response, exc, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.response


def stub_client(**kw):
    return SimpleNamespace(messages=StubMessages(**kw))


def _resp(content, stop="tool_use"):
    usage = SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=500,
                            cache_creation_input_tokens=0)
    return SimpleNamespace(content=content, stop_reason=stop, usage=usage, stop_details=None)


def _http_error(cls, code):
    req = httpx.Request("POST", "https://api.example.invalid/v1/messages")
    return cls("boom", response=httpx.Response(code, request=req), body=None)


def test_request_shape_and_parsing():
    block = SimpleNamespace(type="tool_use", id="t1", name="click", input={"ref": "e3"})
    client = stub_client(response=_resp([SimpleNamespace(type="thinking", thinking=""), block]))
    m = AnthropicModel("claude-haiku-5-5", client=client)
    reply = m.complete("sys", [Part("text", "hi"), Part("image", png=b"\x89PNG")], [{"name": "click"}])
    kw = client.messages.kwargs
    assert kw["model"] == "claude-haiku-5-5"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["messages"][0]["content"][1]["type"] == "image"
    assert "temperature" not in kw and "fallbacks" not in kw
    assert kw["output_config"] == {"effort": "medium"}
    assert reply.calls[0].name == "click" and reply.calls[0].args == {"ref": "e3"}
    assert reply.usage.cache_read_tokens == 500


def test_refusal_is_an_error_not_an_answer():
    resp = _resp([], stop="refusal")
    resp.stop_details = SimpleNamespace(category="cyber")
    reply = AnthropicModel(client=stub_client(response=resp)).complete("s", [Part("text", "x")], [])
    assert reply.error == "refusal (cyber)" and not reply.calls


def test_errors_are_reduced_to_class_and_status():
    m = AnthropicModel(client=stub_client(exc=_http_error(anthropic.RateLimitError, 429)))
    assert m.complete("s", [], []).error == "RateLimitError (HTTP 429)"
    m = AnthropicModel(client=stub_client(exc=_http_error(anthropic.AuthenticationError, 401)))
    with pytest.raises(FatalModelError):
        m.complete("s", [], [])


def test_unknown_model_needs_a_price():
    with pytest.raises(ValueError):
        AnthropicModel("claude-unknown", client=stub_client())


def test_cost_math():
    u = Usage(input_tokens=1_000_000, output_tokens=1_000_000, cache_read_tokens=1_000_000, cache_write_tokens=0)
    p = PRICES["claude-haiku-5-5"]
    assert cost_usd("claude-haiku-5-5", u) == pytest.approx(p[0] + p[1] + p[2])
    assert worst_case_usd("claude-haiku-5-5", 1000, 4000) >= cost_usd(
        "claude-haiku-5-5", Usage(input_tokens=1000, output_tokens=4000))


def test_estimate_counts_images():
    a = estimate_input_tokens("s", [Part("text", "x" * 300)], [])
    b = estimate_input_tokens("s", [Part("text", "x" * 300), Part("image", png=b"")], [])
    assert b - a >= 1000
