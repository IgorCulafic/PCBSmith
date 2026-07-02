from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.evidence import (
    DatasheetExtractionError,
    EvidenceExtractionJob,
    LlmDatasheetExtractor,
    OpenAICompatibleDatasheetClient,
    build_extraction_prompt,
    parse_facts_payload,
)


def _job(role: str = "indicator_led") -> EvidenceExtractionJob:
    return EvidenceExtractionJob(
        status="pending_extraction",
        component_manufacturer="Example",
        component_part_number="EX-LED-0603",
        role=role,
        local_path="datasheets/example.pdf",
        sha256="test-sha",
        source_url="https://example.invalid/example.pdf",
        created_at="2026-07-02",
    )


class FakePdfClient:
    supports_pdf = True

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []
        self.pdf_payloads: list[bytes | None] = []

    def request_facts(
        self,
        *,
        prompt: str,
        pdf_bytes: bytes | None,
        document_text: str | None,
    ) -> str:
        self.prompts.append(prompt)
        self.pdf_payloads.append(pdf_bytes)
        return self.response


class FailingClient:
    supports_pdf = True

    def request_facts(
        self,
        *,
        prompt: str,
        pdf_bytes: bytes | None,
        document_text: str | None,
    ) -> str:
        raise DatasheetExtractionError("provider unavailable")


GOOD_RESPONSE = json.dumps(
    {
        "facts": [
            {
                "name": "forward_voltage_v_typ",
                "value": 2.0,
                "unit": "V",
                "conditions": "IF=20mA",
                "page": 3,
                "table": "Electro-optical characteristics",
            },
            {
                "name": "forward_current_ma_max",
                "value": 25,
                "unit": "mA",
                "conditions": None,
                "page": 2,
                "table": "Absolute maximum ratings",
            },
            {
                "name": "made_up_fact",
                "value": 1.0,
                "unit": None,
                "conditions": None,
                "page": None,
                "table": None,
            },
        ],
        "notes": ["Values taken from the -SRC variant column."],
    }
)


def _write_pdf_placeholder(tmp_path: Path) -> Path:
    pdf = tmp_path / "example.pdf"
    pdf.write_bytes(b"%PDF placeholder bytes")
    return pdf


def test_extractor_builds_facts_with_locators_and_confidence(tmp_path: Path) -> None:
    client = FakePdfClient(GOOD_RESPONSE)
    extractor = LlmDatasheetExtractor(client)
    pdf = _write_pdf_placeholder(tmp_path)

    result = extractor.extract(pdf, _job())

    assert result.status == "machine_extracted"
    assert client.pdf_payloads == [b"%PDF placeholder bytes"]
    names = {fact.name for fact in result.facts}
    assert names == {"forward_voltage_v_typ", "forward_current_ma_max"}
    fv = next(fact for fact in result.facts if fact.name == "forward_voltage_v_typ")
    assert fv.value == 2.0
    assert fv.conditions == "IF=20mA"
    assert fv.locator.page == 3
    assert fv.locator.local_file == "datasheets/example.pdf"
    assert fv.confidence == "machine_extracted"
    assert any("made_up_fact" in finding for finding in result.findings)
    assert any(finding.startswith("Model note:") for finding in result.findings)


def test_extractor_reports_missing_required_facts(tmp_path: Path) -> None:
    partial = json.dumps(
        {
            "facts": [
                {
                    "name": "forward_voltage_v_typ",
                    "value": 2.1,
                    "unit": "V",
                    "conditions": None,
                    "page": 3,
                    "table": None,
                }
            ],
            "notes": [],
        }
    )
    extractor = LlmDatasheetExtractor(FakePdfClient(partial))

    result = extractor.extract(_write_pdf_placeholder(tmp_path), _job())

    assert result.status == "machine_extracted"
    assert any("forward_current_ma_max" in finding for finding in result.findings)


def test_extractor_fails_on_unparseable_response(tmp_path: Path) -> None:
    extractor = LlmDatasheetExtractor(FakePdfClient("I could not find the datasheet values."))

    result = extractor.extract(_write_pdf_placeholder(tmp_path), _job())

    assert result.status == "failed"
    assert result.facts == ()


def test_extractor_fails_when_provider_errors(tmp_path: Path) -> None:
    extractor = LlmDatasheetExtractor(FailingClient())

    result = extractor.extract(_write_pdf_placeholder(tmp_path), _job())

    assert result.status == "failed"
    assert any("provider unavailable" in finding for finding in result.findings)


def test_extractor_requests_generic_facts_for_unknown_role(tmp_path: Path) -> None:
    client = FakePdfClient(GOOD_RESPONSE)
    extractor = LlmDatasheetExtractor(client)

    result = extractor.extract(_write_pdf_placeholder(tmp_path), _job(role="buck_inductor"))

    assert any("no curated fact list" in finding for finding in result.findings)
    assert "resistance_ohms" in client.prompts[0]


def test_prompt_names_component_role_and_required_facts() -> None:
    prompt = build_extraction_prompt(_job(), ("forward_voltage_v_typ",))

    assert "Example EX-LED-0603" in prompt
    assert "indicator_led" in prompt
    assert "forward_voltage_v_typ" in prompt
    assert "Never guess" in prompt


def test_parse_facts_payload_strips_markdown_fences() -> None:
    raw = f"Here you go:\n```json\n{GOOD_RESPONSE}\n```\nLet me know!"

    payload = parse_facts_payload(raw)

    assert len(payload["facts"]) == 3


def test_parse_facts_payload_accepts_bare_list() -> None:
    raw = json.dumps(
        [
            {
                "name": "resistance_ohms",
                "value": 10000,
                "unit": "ohm",
                "conditions": None,
                "page": 1,
                "table": None,
            }
        ]
    )

    payload = parse_facts_payload(raw)

    assert payload["facts"][0]["name"] == "resistance_ohms"


def test_parse_facts_payload_rejects_prose() -> None:
    with pytest.raises(ValueError):
        parse_facts_payload("The forward voltage is 2.0 V at 20 mA.")


class RecordingChatTransport:
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


def test_openai_compatible_client_posts_chat_completion() -> None:
    transport = RecordingChatTransport(
        {"choices": [{"message": {"role": "assistant", "content": GOOD_RESPONSE}}]}
    )
    client = OpenAICompatibleDatasheetClient(
        transport=transport,
        base_url="http://127.0.0.1:5001",
        model="local-model",
    )

    raw = client.request_facts(
        prompt="Extract facts.",
        pdf_bytes=None,
        document_text="[page 1]\nForward voltage 2.0 V",
    )

    url, headers, payload = transport.calls[0]
    assert raw == GOOD_RESPONSE
    assert url == "http://127.0.0.1:5001/v1/chat/completions"
    assert headers["Content-Type"] == "application/json"
    assert payload["model"] == "local-model"
    messages = payload["messages"]
    assert isinstance(messages, list)
    assert "Forward voltage 2.0 V" in messages[0]["content"]


def test_openai_compatible_client_requires_document_text() -> None:
    client = OpenAICompatibleDatasheetClient(
        transport=RecordingChatTransport({}),
        base_url="http://127.0.0.1:5001",
        model="local-model",
    )

    with pytest.raises(DatasheetExtractionError):
        client.request_facts(prompt="Extract facts.", pdf_bytes=None, document_text=None)


def test_openai_compatible_client_rejects_empty_choices() -> None:
    client = OpenAICompatibleDatasheetClient(
        transport=RecordingChatTransport({"choices": []}),
        base_url="http://127.0.0.1:5001",
        model="local-model",
    )

    with pytest.raises(DatasheetExtractionError):
        client.request_facts(
            prompt="Extract facts.",
            pdf_bytes=None,
            document_text="text",
        )
