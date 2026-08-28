from __future__ import annotations


def test_fake_provider_contract() -> None:
    class FakeProvider:
        def complete(self, prompt: str) -> str:
            return "{}"

    provider = FakeProvider()

    assert provider.complete("x") == "{}"
