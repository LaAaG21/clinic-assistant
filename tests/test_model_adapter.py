"""Configured fake behavior, immutable inputs, and no credential/network use."""

import asyncio
import socket

import pytest

from clinic_assistant.model_adapter import FakeModelAdapter, ModelAdapter, ModelMessage

MESSAGES = (
    ModelMessage("system", "Return the requested structured output."),
    ModelMessage("user", 'Question and supplied evidence: {"source_id":"hours.md"}'),
    ModelMessage("assistant", "Previous reply"),
)


@pytest.mark.parametrize("output", ['{"intent":"book"}', "plain reply", "", "bad JSON"])
def test_exact_repeatable_output_and_preserved_input(output: str) -> None:
    fake = FakeModelAdapter(output)
    adapter: ModelAdapter = fake

    async def exercise() -> None:
        assert await adapter.generate(MESSAGES) == output
        assert await adapter.generate(MESSAGES) == output

    asyncio.run(exercise())
    assert fake.calls == [MESSAGES, MESSAGES]
    assert fake.calls[0] is MESSAGES
    assert fake.calls[0][1].content.endswith('{"source_id":"hours.md"}')


@pytest.mark.parametrize(
    "failure", [TimeoutError("controlled timeout"), RuntimeError("controlled failure")]
)
def test_exact_repeatable_failure(failure: Exception) -> None:
    fake = FakeModelAdapter(failure)

    async def exercise() -> None:
        for _ in range(2):
            with pytest.raises(type(failure)) as error:
                await fake.generate(MESSAGES)
            assert error.value is failure

    asyncio.run(exercise())
    assert fake.calls == [MESSAGES, MESSAGES]


def test_instances_and_calls_are_independent() -> None:
    first, second = FakeModelAdapter("first"), FakeModelAdapter("second")
    assert asyncio.run(first.generate(())) == "first"
    assert second.calls == []
    assert asyncio.run(second.generate(MESSAGES)) == "second"
    assert first.calls == [()]
    assert second.calls == [MESSAGES]


def test_no_credentials_or_outgoing_network(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("The fake attempted network access")

    # Initialize the event loop before guarding sockets (Windows uses local
    # sockets during loop setup); no provider operation is permitted afterward.
    with asyncio.Runner() as runner, monkeypatch.context() as guard:
        guard.setattr(socket, "create_connection", forbidden)
        guard.setattr(socket, "getaddrinfo", forbidden)
        guard.setattr(socket.socket, "connect", forbidden)
        guard.setattr(socket.socket, "connect_ex", forbidden)
        assert (
            runner.run(FakeModelAdapter("offline reply").generate(MESSAGES))
            == "offline reply"
        )
