"""Topology forge: LLM proposes, the deterministic verifier disposes.

Track 8.3 (docs/hardening-and-generalization-plan.md), the
PCBSchemaGen/Diode pattern: a language model writes a TOPOLOGY SPEC -
components with roles/values/footprints plus a pin->net map - and a
deterministic verifier with pin-level error localization gates it,
feeding findings back for refinement. PCBSchemaGen reports 81.3% pass
rates from a local Gemma-4-31B under exactly this shape; the verifier,
not the model, carries the correctness.

The model NEVER touches board files or the pipeline: an accepted spec
is raw material a developer turns into a real topology module, which
then faces the full authority chain and the golden suite. This module
is the loop mechanics plus the spec verifier; any completion client
(Anthropic, llama.cpp/KoboldCpp, a scripted test double) plugs in via
the one-method protocol.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

SPEC_CONTRACT = """You design electronics as JSON. Reply with ONE json
object and nothing else, shaped exactly like:
{
  "components": [
    {"reference": "R1", "role": "led_series_resistor", "value": "1k",
     "footprint": "Resistor_SMD:R_0603_1608Metric"}
  ],
  "pin_nets": {"R1": {"1": "VIN", "2": "LED_A"}}
}
Rules: every reference unique; footprint must be a real KiCad
"Library:Name" id; every pin of every part assigned to a net; every
net must connect at least two pins; values are real part values."""


@dataclass(frozen=True)
class ForgeResult:
    status: str  # accepted | rejected | invalid
    iterations: int
    spec: dict[str, object] | None
    findings_history: tuple[tuple[str, ...], ...] = field(default=())


def verify_topology_spec(spec: dict[str, object]) -> tuple[str, ...]:
    """Deterministic gate with pin-level localization. Empty = accepted."""
    from pcbsmith.kicad.library import FootprintLibraryError, load_footprint

    findings: list[str] = []
    components = spec.get("components")
    pin_nets = spec.get("pin_nets")
    if not isinstance(components, list) or not components:
        return ('spec: "components" must be a non-empty list',)
    if not isinstance(pin_nets, dict):
        return ('spec: "pin_nets" must be an object keyed by reference',)

    seen: dict[str, dict[str, object]] = {}
    pads_by_ref: dict[str, set[str]] = {}
    for component in components:
        reference = str(component.get("reference", ""))
        if not reference:
            findings.append("component without a reference")
            continue
        if reference in seen:
            findings.append(f"{reference}: duplicate reference")
            continue
        seen[reference] = component
        for key in ("role", "value", "footprint"):
            if not component.get(key):
                findings.append(f"{reference}: missing {key}")
        footprint = component.get("footprint", "")
        if footprint:
            try:
                spec_fp = load_footprint(footprint).spec
            except (FootprintLibraryError, ValueError) as exc:
                findings.append(f"{reference}: footprint {footprint!r}: {exc}")
                continue
            pads_by_ref[reference] = {
                pad.name for pad in spec_fp.pads if pad.name
            }

    net_members: dict[str, list[str]] = {}
    for reference, pins in pin_nets.items():
        if reference not in seen:
            findings.append(
                f"pin_nets names {reference}, which is not a component"
            )
            continue
        known_pads = pads_by_ref.get(reference)
        for pin, net in pins.items():
            if known_pads is not None and str(pin) not in known_pads:
                findings.append(
                    f"{reference}.{pin}: footprint has no such pad "
                    f"(pads: {', '.join(sorted(known_pads))})"
                )
            net_members.setdefault(str(net), []).append(f"{reference}.{pin}")
    for reference, pads in pads_by_ref.items():
        assigned = set(map(str, pin_nets.get(reference, {})))
        for pad in sorted(pads - assigned):
            findings.append(
                f"{reference}.{pad}: pad has no net (assign it or drop "
                "the part)"
            )
    for net, members in sorted(net_members.items()):
        if len(members) < 2:
            findings.append(
                f"net {net}: only {members[0]} connects to it (nets need "
                "two or more pins)"
            )
    return tuple(findings)


def extract_json(text: str) -> dict[str, object] | None:
    """The first parseable JSON object in a completion, fences included."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    brace = text.find("{")
    if brace != -1:
        candidates.append(text[brace: text.rfind("}") + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def forge_topology(
    request: str,
    complete: Callable[[str], str],
    *,
    max_iterations: int = 3,
) -> ForgeResult:
    """Propose-verify-refine until the verifier accepts or patience ends.

    `complete` is any prompt->text callable: an API client, a local
    llama.cpp server, or a scripted double in tests."""
    history: list[tuple[str, ...]] = []
    spec: dict[str, object] | None = None
    for iteration in range(1, max_iterations + 1):
        prompt = f"{SPEC_CONTRACT}\n\nDesign request: {request}\n"
        if spec is not None and history:
            prompt += (
                "\nYour previous attempt:\n"
                + json.dumps(spec, indent=1)
                + "\nA deterministic verifier rejected it. Fix EXACTLY "
                "these findings and reply with the full corrected JSON:\n"
                + "\n".join(f"- {finding}" for finding in history[-1])
                + "\n"
            )
        reply = complete(prompt)
        spec = extract_json(reply)
        if spec is None:
            history.append(("reply contained no parseable JSON object",))
            continue
        findings = verify_topology_spec(spec)
        history.append(findings)
        if not findings:
            return ForgeResult(
                status="accepted", iterations=iteration, spec=spec,
                findings_history=tuple(history),
            )
    return ForgeResult(
        status="rejected" if spec is not None else "invalid",
        iterations=max_iterations, spec=spec,
        findings_history=tuple(history),
    )


def openai_compatible_client(
    endpoint: str, *, max_tokens: int = 900, temperature: float = 0.2
) -> Callable[[str], str]:
    """A `complete` callable for any OpenAI-compatible /v1/completions
    server (llama.cpp, KoboldCpp, llama-swap). Standard library only."""
    import urllib.request

    def complete(prompt: str) -> str:
        payload = json.dumps(
            {
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint.rstrip("/") + "/v1/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=1800) as response:
            body = json.loads(response.read().decode("utf-8"))
        return str(body["choices"][0].get("text", ""))

    return complete
