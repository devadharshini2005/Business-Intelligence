import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chat_agent  # noqa: E402


class FakeCompletions:
    def __init__(self):
        self.request_args = None

    def create(self, **request_args):
        self.request_args = request_args
        message = SimpleNamespace(tool_calls=[], content="ok")
        choice = SimpleNamespace(finish_reason="stop", message=message)
        return SimpleNamespace(choices=[choice])


@pytest.mark.parametrize(
    ("deployment", "expected_token_argument"),
    [("gpt-5", "max_completion_tokens"), ("gpt-4.1", "max_tokens")],
)
def test_openai_request_uses_deployment_compatible_token_argument(
    monkeypatch, deployment, expected_token_argument
):
    monkeypatch.setattr(chat_agent, "AZURE_DEPLOYMENT", deployment)
    completions = FakeCompletions()
    agent = chat_agent.ChatAgent.__new__(chat_agent.ChatAgent)
    agent.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = asyncio.run(agent._loop_openai([], [], [], set(), None, []))

    assert result["answer"] == "ok"
    assert completions.request_args[expected_token_argument] == 8000
    other_token_argument = (
        "max_tokens" if expected_token_argument == "max_completion_tokens" else "max_completion_tokens"
    )
    assert other_token_argument not in completions.request_args
    if deployment == "gpt-5":
        assert "temperature" not in completions.request_args
    else:
        assert completions.request_args["temperature"] == 0
