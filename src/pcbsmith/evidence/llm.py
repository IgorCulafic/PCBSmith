from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol
from urllib import request

from pcbsmith.evidence.extraction import EvidenceExtractionResult
from pcbsmith.evidence.models import EvidenceExtractionJob, EvidenceFact, EvidenceLocator

ANTHROPIC_DEFAULT_MODEL = "claude-opus-4-8"
LOCAL_DEFAULT_BASE_URL = "http://127.0.0.1:5001"
LOCAL_DEFAULT_MODEL = "local-model"
LOCAL_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"

FACT_DEFINITIONS: dict[str, str] = {
    "resistance_ohms": "Nominal resistance in ohms as a number.",
    "power_rating_w": "Rated power dissipation in watts as a number.",
    "tolerance_percent": "Resistance tolerance in percent as a number (1 means +/-1%).",
    "capacitance_f": "Nominal capacitance in farads as a number (100nF is 1e-07).",
    "voltage_rating_v": "Rated DC working voltage in volts as a number.",
    "dielectric": "Dielectric class as a string (for example X7R or C0G).",
    "forward_voltage_v_typ": (
        "Typical forward voltage in volts as a number, with the test current in conditions."
    ),
    "forward_current_ma_max": (
        "Maximum continuous DC forward current in milliamps as a number."
    ),
}

ROLE_FACT_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "divider_top": ("resistance_ohms", "power_rating_w", "tolerance_percent"),
    "divider_bottom": ("resistance_ohms", "power_rating_w", "tolerance_percent"),
    "led_current_limit": ("resistance_ohms", "power_rating_w", "tolerance_percent"),
    "highpass_series_capacitor": ("capacitance_f", "voltage_rating_v", "dielectric"),
    "indicator_led": ("forward_voltage_v_typ", "forward_current_ma_max"),
}

FACTS_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {
                        "anyOf": [
                            {"type": "number"},
                            {"type": "string"},
                            {"type": "boolean"},
                        ]
                    },
                    "unit": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "conditions": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "page": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    "table": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
                "required": ["name", "value", "unit", "conditions", "page", "table"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["facts", "notes"],
    "additionalProperties": False,
}


class DatasheetExtractionError(RuntimeError):
    pass


class DatasheetChatClient(Protocol):
    @property
    def supports_pdf(self) -> bool:
        ...

    def request_facts(
        self,
        *,
        prompt: str,
        pdf_bytes: bytes | None,
        document_text: str | None,
    ) -> str:
        ...


def build_extraction_prompt(
    job: EvidenceExtractionJob,
    fact_names: tuple[str, ...],
) -> str:
    fact_lines = "\n".join(
        f"- {name}: {FACT_DEFINITIONS.get(name, 'Value as stated in the datasheet.')}"
        for name in fact_names
    )
    return (
        "You are extracting electrical facts from a component datasheet for an "
        "electronics design validation pipeline.\n"
        f"Component: {job.component_manufacturer} {job.component_part_number}\n"
        f"Circuit role: {job.role}\n\n"
        "Report ONLY these facts, using exactly these names:\n"
        f"{fact_lines}\n\n"
        "Rules:\n"
        "- Only report values that are actually stated in the datasheet. Never guess or "
        "use typical industry values. Omit a fact if the datasheet does not state it.\n"
        "- Record the datasheet page number and table or section title where each value "
        "was found.\n"
        "- Record test conditions (for example IF=20mA) in the conditions field when the "
        "datasheet states them.\n"
        "- If a value is given per part-number variant, use the variant matching the "
        "component above; if no variant matches, omit the fact and explain in notes.\n\n"
        "Respond with a single JSON object of this shape and nothing else:\n"
        '{"facts": [{"name": "...", "value": 0, "unit": "...", "conditions": null, '
        '"page": 1, "table": "..."}], "notes": ["..."]}'
    )


def parse_facts_payload(raw: str) -> dict[str, Any]:
    candidates: list[str] = []
    text = raw.strip()
    candidates.append(text)
    if "```" in text:
        for segment in text.split("```")[1::2]:
            cleaned = segment.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            candidates.append(cleaned)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            decoded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, list):
            return {"facts": decoded, "notes": []}
        if isinstance(decoded, dict):
            if "facts" in decoded:
                return decoded
            if "name" in decoded and "value" in decoded:
                return {"facts": [decoded], "notes": []}
    raise ValueError("Model response did not contain a parseable facts JSON object.")


class LlmDatasheetExtractor:
    def __init__(
        self,
        client: DatasheetChatClient,
        *,
        text_char_limit: int = 60_000,
    ) -> None:
        self._client = client
        self._text_char_limit = text_char_limit

    def extract(
        self,
        path: Path,
        job: EvidenceExtractionJob,
    ) -> EvidenceExtractionResult:
        fact_names = ROLE_FACT_REQUIREMENTS.get(job.role)
        findings: list[str] = []
        if fact_names is None:
            fact_names = tuple(FACT_DEFINITIONS)
            findings.append(
                f"Role {job.role} has no curated fact list; requested the generic fact set."
            )
        prompt = build_extraction_prompt(job, fact_names)

        try:
            if self._client.supports_pdf:
                raw = self._client.request_facts(
                    prompt=prompt,
                    pdf_bytes=path.read_bytes(),
                    document_text=None,
                )
            else:
                document_text = _read_pdf_text(path, self._text_char_limit)
                raw = self._client.request_facts(
                    prompt=prompt,
                    pdf_bytes=None,
                    document_text=document_text,
                )
        except DatasheetExtractionError as exc:
            return EvidenceExtractionResult(
                status="failed",
                findings=(*findings, str(exc)),
            )

        try:
            payload = parse_facts_payload(raw)
        except ValueError as exc:
            snippet = raw.strip().replace("\n", " ")[:200]
            return EvidenceExtractionResult(
                status="failed",
                findings=(*findings, f"{exc} Raw response started with: {snippet}"),
            )

        facts, fact_findings = _facts_from_payload(payload, job, fact_names)
        findings.extend(fact_findings)
        for note in payload.get("notes", []):
            if isinstance(note, str) and note.strip():
                findings.append(f"Model note: {note.strip()}")
        if not facts:
            return EvidenceExtractionResult(
                status="failed",
                findings=(*findings, "Extraction did not produce any usable facts."),
            )
        for name in fact_names:
            if all(fact.name != name for fact in facts):
                findings.append(f"Datasheet did not yield a value for {name}.")
        return EvidenceExtractionResult(
            status="machine_extracted",
            facts=tuple(facts),
            findings=tuple(findings),
        )


def _facts_from_payload(
    payload: Mapping[str, Any],
    job: EvidenceExtractionJob,
    fact_names: tuple[str, ...],
) -> tuple[list[EvidenceFact], list[str]]:
    facts: list[EvidenceFact] = []
    findings: list[str] = []
    entries = payload.get("facts")
    if not isinstance(entries, list):
        return facts, ["Model response facts field was not a list."]
    for entry in entries:
        if not isinstance(entry, Mapping):
            findings.append("Skipped a non-object fact entry from the model response.")
            continue
        name = entry.get("name")
        value = entry.get("value")
        if not isinstance(name, str) or not name:
            findings.append("Skipped a fact entry without a name.")
            continue
        if name not in fact_names:
            findings.append(f"Skipped unrequested fact {name} from the model response.")
            continue
        if not isinstance(value, float | int | str | bool) or value is None:
            findings.append(f"Skipped fact {name} with an unusable value.")
            continue
        page = entry.get("page")
        table = entry.get("table")
        unit = entry.get("unit")
        conditions = entry.get("conditions")
        facts.append(
            EvidenceFact(
                name=name,
                value=value if isinstance(value, str | bool) else float(value),
                unit=unit if isinstance(unit, str) else None,
                conditions=conditions if isinstance(conditions, str) else None,
                locator=EvidenceLocator(
                    local_file=job.local_path,
                    page=page if isinstance(page, int) else None,
                    table=table if isinstance(table, str) else None,
                ),
                confidence="machine_extracted",
            )
        )
    return facts, findings


def _read_pdf_text(path: Path, char_limit: int) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DatasheetExtractionError(
            "pypdf is required for text extraction with non-PDF-capable models. "
            "Install the extraction extra: pip install 'pcbsmith[extraction]'."
        ) from exc
    try:
        reader = PdfReader(str(path))
        pages = [
            f"[page {index}]\n{page.extract_text() or ''}"
            for index, page in enumerate(reader.pages, start=1)
        ]
    except Exception as exc:  # noqa: BLE001 - pypdf raises many concrete types
        raise DatasheetExtractionError(f"PDF text extraction failed: {exc}") from exc
    text = "\n\n".join(pages).strip()
    if not text:
        raise DatasheetExtractionError(
            "PDF contained no extractable text; it is likely a scanned document. "
            "Use a PDF-capable provider (anthropic) or add OCR."
        )
    if len(text) > char_limit:
        text = text[:char_limit] + "\n[truncated]"
    return text


class AnthropicDatasheetClient:
    supports_pdf = True

    def __init__(
        self,
        *,
        model: str = ANTHROPIC_DEFAULT_MODEL,
        max_tokens: int = 16_000,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._client: Any = None

    def request_facts(
        self,
        *,
        prompt: str,
        pdf_bytes: bytes | None,
        document_text: str | None,
    ) -> str:
        client = self._anthropic_client()
        content: list[dict[str, Any]] = []
        if pdf_bytes is not None:
            content.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.standard_b64encode(pdf_bytes).decode("ascii"),
                    },
                }
            )
        text = prompt if document_text is None else f"{prompt}\n\nDatasheet text:\n{document_text}"
        content.append({"type": "text", "text": text})
        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                thinking={"type": "adaptive"},
                output_config={
                    "format": {"type": "json_schema", "schema": FACTS_RESPONSE_SCHEMA}
                },
                messages=[{"role": "user", "content": content}],
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a structured finding
            raise DatasheetExtractionError(f"Anthropic API request failed: {exc}") from exc
        if response.stop_reason == "refusal":
            raise DatasheetExtractionError("Anthropic API refused the extraction request.")
        if response.stop_reason == "max_tokens":
            raise DatasheetExtractionError(
                "Anthropic API response was truncated at max_tokens."
            )
        for block in response.content:
            if block.type == "text":
                return str(block.text)
        raise DatasheetExtractionError("Anthropic API response contained no text block.")

    def _anthropic_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise DatasheetExtractionError(
                    "The anthropic package is required for the paid extraction provider. "
                    "Install the extraction extra: pip install 'pcbsmith[extraction]'."
                ) from exc
            self._client = anthropic.Anthropic()
        return self._client


class ChatJsonTransport(Protocol):
    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
    ) -> Mapping[str, Any]:
        ...


class UrlLibChatTransport:
    def __init__(self, *, timeout_seconds: float = 120.0) -> None:
        self._timeout_seconds = timeout_seconds

    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
    ) -> Mapping[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                text = response.read().decode("utf-8")
        except OSError as exc:
            raise DatasheetExtractionError(f"Local AI HTTP request failed: {exc}") from exc
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DatasheetExtractionError("Local AI response was not valid JSON.") from exc
        if not isinstance(decoded, Mapping):
            raise DatasheetExtractionError("Local AI response JSON was not an object.")
        return decoded


class OpenAICompatibleDatasheetClient:
    supports_pdf = False

    def __init__(
        self,
        *,
        transport: ChatJsonTransport,
        base_url: str = LOCAL_DEFAULT_BASE_URL,
        model: str = LOCAL_DEFAULT_MODEL,
        api_key: str | None = None,
        max_tokens: int = 4_096,
    ) -> None:
        self._transport = transport
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._max_tokens = max_tokens

    def request_facts(
        self,
        *,
        prompt: str,
        pdf_bytes: bytes | None,
        document_text: str | None,
    ) -> str:
        if document_text is None:
            raise DatasheetExtractionError(
                "The OpenAI-compatible provider requires extracted datasheet text."
            )
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        response = self._transport.post_json(
            f"{self._base_url}{LOCAL_CHAT_COMPLETIONS_PATH}",
            headers=headers,
            payload={
                "model": self._model,
                "max_tokens": self._max_tokens,
                "temperature": 0,
                "messages": [
                    {
                        "role": "user",
                        "content": f"{prompt}\n\nDatasheet text:\n{document_text}",
                    }
                ],
            },
        )
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise DatasheetExtractionError("Local AI response contained no choices.")
        first = choices[0]
        message = first.get("message") if isinstance(first, Mapping) else None
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str) or not content.strip():
            raise DatasheetExtractionError("Local AI response contained no message content.")
        return content
