from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, Protocol
from urllib import parse, request

from pcbsmith.evidence.models import EvidenceAcquisitionRequest, EvidenceSourceCandidate

NEXAR_GRAPHQL_ENDPOINT = "https://api.nexar.com/graphql/"
NEXAR_TOKEN_ENDPOINT = "https://identity.nexar.com/connect/token"
_SUP_SEARCH_MPN_QUERY = """
query PCBSmithSupSearchMpn($q: String!, $limit: Int!) {
  supSearchMpn(q: $q, limit: $limit) {
    results {
      part {
        mpn
        name
        manufacturer {
          name
          homepageUrl
        }
        bestDatasheet {
          url
        }
      }
    }
  }
}
"""


class NexarProviderError(RuntimeError):
    pass


class NexarJsonTransport(Protocol):
    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
    ) -> Mapping[str, Any]:
        ...


class NexarTokenTransport(Protocol):
    def post_form(
        self,
        url: str,
        *,
        headers: dict[str, str],
        data: dict[str, str],
    ) -> Mapping[str, Any]:
        ...


class UrlLibNexarTransport:
    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
    ) -> Mapping[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        return _read_json(
            request.Request(
                url,
                data=body,
                headers=headers,
                method="POST",
            )
        )

    def post_form(
        self,
        url: str,
        *,
        headers: dict[str, str],
        data: dict[str, str],
    ) -> Mapping[str, Any]:
        body = parse.urlencode(data).encode("utf-8")
        return _read_json(
            request.Request(
                url,
                data=body,
                headers=headers,
                method="POST",
            )
        )


class NexarClientCredentialsTokenProvider:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        transport: NexarTokenTransport,
        token_endpoint: str = NEXAR_TOKEN_ENDPOINT,
        scope: str = "supply.domain",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport = transport
        self._token_endpoint = token_endpoint
        self._scope = scope

    def __call__(self) -> str:
        response = self._transport.post_form(
            self._token_endpoint,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": self._scope,
            },
        )
        access_token = response.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise NexarProviderError("Nexar token response did not include access_token.")
        return access_token


class NexarSupplyProvider:
    def __init__(
        self,
        *,
        token_provider: Callable[[], str],
        transport: NexarJsonTransport,
        endpoint: str = NEXAR_GRAPHQL_ENDPOINT,
        limit: int = 3,
    ) -> None:
        if limit <= 0:
            raise ValueError("Nexar result limit must be positive")
        self._token_provider = token_provider
        self._transport = transport
        self._endpoint = endpoint
        self._limit = limit

    def search(
        self,
        request: EvidenceAcquisitionRequest,
    ) -> tuple[EvidenceSourceCandidate, ...]:
        response = self._transport.post_json(
            self._endpoint,
            headers={
                "Authorization": f"Bearer {self._token_provider()}",
                "Content-Type": "application/json",
            },
            payload={
                "query": _SUP_SEARCH_MPN_QUERY,
                "variables": {
                    "q": request.part_number or request.query,
                    "limit": self._limit,
                },
            },
        )
        _raise_for_graphql_errors(response)
        results = _get_results(response)
        candidates: list[EvidenceSourceCandidate] = []
        for result in results:
            part = _mapping_or_none(result.get("part")) if isinstance(result, Mapping) else None
            if part is None:
                continue
            candidate = _candidate_from_part(part, role=request.role)
            if candidate is not None:
                candidates.append(candidate)
        return tuple(candidates)


def _raise_for_graphql_errors(response: Mapping[str, Any]) -> None:
    errors = response.get("errors")
    if not isinstance(errors, list) or not errors:
        return
    messages = []
    for error in errors:
        if isinstance(error, Mapping) and isinstance(error.get("message"), str):
            messages.append(error["message"])
    raise NexarProviderError("; ".join(messages) if messages else "Nexar GraphQL error")


def _get_results(response: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    data = _mapping_or_none(response.get("data"))
    if data is None:
        return ()
    search = _mapping_or_none(data.get("supSearchMpn"))
    if search is None:
        return ()
    results = search.get("results")
    if not isinstance(results, list):
        return ()
    return tuple(result for result in results if isinstance(result, Mapping))


def _candidate_from_part(
    part: Mapping[str, Any],
    *,
    role: str,
) -> EvidenceSourceCandidate | None:
    mpn = _string_or_none(part.get("mpn"))
    if mpn is None:
        return None
    manufacturer = _mapping_or_none(part.get("manufacturer"))
    manufacturer_name = _string_or_none(manufacturer.get("name")) if manufacturer else None
    source_url = _string_or_none(manufacturer.get("homepageUrl")) if manufacturer else None
    return EvidenceSourceCandidate(
        provider="nexar",
        manufacturer=manufacturer_name or "Unknown manufacturer",
        part_number=mpn,
        role=role,
        source_url=source_url or NEXAR_GRAPHQL_ENDPOINT,
        datasheet_url=_datasheet_url(part),
        value=_string_or_none(part.get("name")) or mpn,
        license_status="local_cache_only",
    )


def _datasheet_url(part: Mapping[str, Any]) -> str | None:
    best_datasheet = _mapping_or_none(part.get("bestDatasheet"))
    if best_datasheet is not None:
        url = _string_or_none(best_datasheet.get("url"))
        if url is not None:
            return url
    collections = part.get("documentCollections")
    if isinstance(collections, list):
        for collection in collections:
            url = _first_nested_url(collection)
            if url is not None:
                return url
    return None


def _first_nested_url(value: object) -> str | None:
    if isinstance(value, Mapping):
        url = _string_or_none(value.get("url"))
        if url is not None:
            return url
        for child in value.values():
            nested_url = _first_nested_url(child)
            if nested_url is not None:
                return nested_url
    if isinstance(value, list):
        for child in value:
            nested_url = _first_nested_url(child)
            if nested_url is not None:
                return nested_url
    return None


def _mapping_or_none(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _read_json(http_request: request.Request) -> Mapping[str, Any]:
    try:
        with request.urlopen(http_request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except OSError as exc:
        raise NexarProviderError(f"Nexar HTTP request failed: {exc}") from exc
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise NexarProviderError("Nexar HTTP response was not valid JSON.") from exc
    if not isinstance(decoded, Mapping):
        raise NexarProviderError("Nexar HTTP response JSON was not an object.")
    return decoded
