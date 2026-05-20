from __future__ import annotations

import pytest

from pcbsmith.evidence import (
    EvidenceAcquisitionRequest,
    NexarClientCredentialsTokenProvider,
    NexarProviderError,
    NexarSupplyProvider,
)


class RecordingTransport:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str], dict[str, object]]] = []

    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
    ) -> dict:
        self.calls.append((url, headers, payload))
        return self.response


class RecordingTokenTransport:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str], dict[str, str]]] = []

    def post_form(
        self,
        url: str,
        *,
        headers: dict[str, str],
        data: dict[str, str],
    ) -> dict:
        self.calls.append((url, headers, data))
        return self.response


def test_nexar_client_credentials_token_provider_posts_supply_scope_form() -> None:
    transport = RecordingTokenTransport({"access_token": "token-123", "expires_in": 86400})
    token_provider = NexarClientCredentialsTokenProvider(
        client_id="client-id",
        client_secret="client-secret",
        transport=transport,
    )

    token = token_provider()

    url, headers, data = transport.calls[0]
    assert token == "token-123"
    assert url == "https://identity.nexar.com/connect/token"
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert data == {
        "grant_type": "client_credentials",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "scope": "supply.domain",
    }


def test_nexar_token_provider_rejects_response_without_access_token() -> None:
    token_provider = NexarClientCredentialsTokenProvider(
        client_id="client-id",
        client_secret="client-secret",
        transport=RecordingTokenTransport({"error": "invalid_client"}),
    )

    with pytest.raises(NexarProviderError, match="access_token"):
        token_provider()


def test_nexar_provider_posts_graphql_with_bearer_token_and_part_number_query() -> None:
    transport = RecordingTransport(_response_with_part())
    provider = NexarSupplyProvider(
        token_provider=lambda: "token-123",
        transport=transport,
        limit=2,
    )

    candidates = provider.search(
        EvidenceAcquisitionRequest(
            role="indicator_led",
            query="red led",
            manufacturer="Example",
            part_number="EX-LED-0603",
        )
    )

    url, headers, payload = transport.calls[0]
    assert candidates[0].part_number == "EX-LED-0603"
    assert url == "https://api.nexar.com/graphql/"
    assert headers["Authorization"] == "Bearer token-123"
    assert headers["Content-Type"] == "application/json"
    assert "supSearchMpn" in str(payload["query"])
    assert payload["variables"] == {"q": "EX-LED-0603", "limit": 2}


def test_nexar_provider_maps_best_datasheet_to_source_candidate() -> None:
    provider = NexarSupplyProvider(
        token_provider=lambda: "token-123",
        transport=RecordingTransport(_response_with_part()),
    )

    candidates = provider.search(
        EvidenceAcquisitionRequest(role="indicator_led", query="EX-LED-0603")
    )

    assert len(candidates) == 1
    assert candidates[0].provider == "nexar"
    assert candidates[0].manufacturer == "Example Opto"
    assert candidates[0].part_number == "EX-LED-0603"
    assert candidates[0].role == "indicator_led"
    assert candidates[0].value == "Example red LED"
    assert candidates[0].source_url == "https://example.invalid"
    assert candidates[0].datasheet_url == "https://example.invalid/ex-led-0603.pdf"
    assert candidates[0].license_status == "local_cache_only"


def test_nexar_provider_uses_free_text_query_when_part_number_is_missing() -> None:
    transport = RecordingTransport({"data": {"supSearchMpn": {"results": []}}})
    provider = NexarSupplyProvider(
        token_provider=lambda: "token-123",
        transport=transport,
    )

    candidates = provider.search(EvidenceAcquisitionRequest(role="divider_top", query="10k 0603"))

    assert candidates == ()
    assert transport.calls[0][2]["variables"] == {"q": "10k 0603", "limit": 3}


def test_nexar_provider_returns_empty_when_result_has_no_part() -> None:
    provider = NexarSupplyProvider(
        token_provider=lambda: "token-123",
        transport=RecordingTransport({"data": {"supSearchMpn": {"results": [{"part": None}]}}}),
    )

    assert provider.search(EvidenceAcquisitionRequest(role="divider_top", query="10k")) == ()


def test_nexar_provider_raises_for_graphql_errors() -> None:
    provider = NexarSupplyProvider(
        token_provider=lambda: "token-123",
        transport=RecordingTransport({"errors": [{"message": "Bad Credentials"}]}),
    )

    with pytest.raises(NexarProviderError, match="Bad Credentials"):
        provider.search(EvidenceAcquisitionRequest(role="indicator_led", query="red led"))


def _response_with_part() -> dict:
    return {
        "data": {
            "supSearchMpn": {
                "results": [
                    {
                        "part": {
                            "mpn": "EX-LED-0603",
                            "name": "Example red LED",
                            "manufacturer": {
                                "name": "Example Opto",
                                "homepageUrl": "https://example.invalid",
                            },
                            "bestDatasheet": {
                                "url": "https://example.invalid/ex-led-0603.pdf",
                            },
                        }
                    }
                ]
            }
        }
    }
