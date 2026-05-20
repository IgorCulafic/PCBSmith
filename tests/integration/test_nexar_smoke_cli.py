from __future__ import annotations

from pcbsmith.cli import main


def test_nexar_smoke_skips_when_credentials_are_absent(monkeypatch, capsys) -> None:
    monkeypatch.delenv("PCBSMITH_NEXAR_CLIENT_ID", raising=False)
    monkeypatch.delenv("PCBSMITH_NEXAR_CLIENT_SECRET", raising=False)

    exit_code = main(
        [
            "evidence-nexar-smoke",
            "--role",
            "indicator_led",
            "--query",
            "red led",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Skipped Nexar smoke" in captured.out
    assert "PCBSMITH_NEXAR_CLIENT_ID" in captured.out

