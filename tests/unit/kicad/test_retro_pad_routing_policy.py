from __future__ import annotations

from types import SimpleNamespace

import pytest

from pcbsmith.kicad import retro_pad_board
from pcbsmith.kicad.board import BoardGenerationError, BoardLayout, BoardNet, BoardNetlist


def _netlist(*names: str) -> BoardNetlist:
    return BoardNetlist(
        components=(),
        nets=tuple(
            BoardNet(name=name, nodes=((f"{index}A", "1"), (f"{index}B", "1")))
            for index, name in enumerate(names)
        ),
    )


def test_retro_pad_reserves_fine_usb_escape_then_routes_vbus_before_mcu_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def route_board(layout: BoardLayout, _netlist: BoardNetlist, **kwargs: object):
        calls.append(dict(kwargs))
        return SimpleNamespace(
            layout=layout,
            failed=(),
            run_result=SimpleNamespace(passes=()),
        )

    monkeypatch.setattr(retro_pad_board, "route_board", route_board)
    retro_pad_board.route_retro_pad_placement_layout(
        BoardLayout(
            placements=(), segments=(), vias=(), width_mm=10.0, height_mm=10.0
        ),
        _netlist(
            "/VBUS_RAW",
            "/USB_DM_CONN",
            "/USB_DP_CONN",
            "/USB_DM_MCU",
            "/USB_DP_MCU",
        ),
        route_ground_tracks=False,
    )

    assert calls[0]["net_order"] == ("/USB_DM_CONN", "/USB_DP_CONN")
    assert calls[0]["fine_grid_mm"] == 0.05
    assert calls[1]["net_order"] == ("/VBUS_RAW",)
    assert calls[1]["grid_mm"] == 0.4
    assert calls[1]["fine_pitch_nets"] == {}
    assert calls[2]["net_order"] == ("/USB_DM_MCU", "/USB_DP_MCU")


def test_retro_pad_does_not_route_ground_as_a_remaining_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def route_board(layout: BoardLayout, _netlist: BoardNetlist, **kwargs: object):
        calls.append(tuple(kwargs["net_order"]))  # type: ignore[arg-type]
        return SimpleNamespace(
            layout=layout,
            failed=(),
            run_result=SimpleNamespace(passes=()),
        )

    monkeypatch.setattr(retro_pad_board, "route_board", route_board)
    retro_pad_board.route_retro_pad_placement_layout(
        BoardLayout(
            placements=(), segments=(), vias=(), width_mm=10.0, height_mm=10.0
        ),
        _netlist("/GND", "/OTHER"),
    )

    assert calls.count(("/GND",)) == 1
    assert calls.count(("/OTHER",)) == 1


def test_retro_pad_rejects_unknown_checkpoint_net() -> None:
    with pytest.raises(BoardGenerationError, match="unknown nets"):
        retro_pad_board.route_retro_pad_placement_layout(
            BoardLayout(
                placements=(), segments=(), vias=(), width_mm=10.0, height_mm=10.0
            ),
            _netlist("/KNOWN"),
            completed_net_names={"/FOREIGN"},
        )


def test_retro_pad_checkpoint_observer_receives_exact_completed_net_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoints: list[tuple[str, frozenset[str]]] = []

    def route_board(layout: BoardLayout, _netlist: BoardNetlist, **_kwargs: object):
        return SimpleNamespace(
            layout=layout,
            failed=(),
            run_result=SimpleNamespace(passes=()),
        )

    monkeypatch.setattr(retro_pad_board, "route_board", route_board)
    retro_pad_board.route_retro_pad_placement_layout(
        BoardLayout(
            placements=(), segments=(), vias=(), width_mm=10.0, height_mm=10.0
        ),
        _netlist("/VBUS_RAW", "/OTHER"),
        route_ground_tracks=False,
        checkpoint_observer=lambda label, _layout, completed: checkpoints.append(
            (label, completed)
        ),
    )

    assert checkpoints[0] == ("raw VBUS", frozenset({"/VBUS_RAW"}))
    assert checkpoints[-1] == (
        "remaining signals",
        frozenset({"/VBUS_RAW", "/OTHER"}),
    )


def test_clock_precedes_early_power_and_matrix_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def route_board(layout: BoardLayout, _netlist: BoardNetlist, **kwargs: object):
        calls.append(tuple(kwargs["net_order"]))  # type: ignore[arg-type]
        return SimpleNamespace(
            layout=layout,
            failed=(),
            run_result=SimpleNamespace(passes=()),
        )

    monkeypatch.setattr(retro_pad_board, "route_board", route_board)
    retro_pad_board.route_retro_pad_placement_layout(
        BoardLayout(
            placements=(), segments=(), vias=(), width_mm=10.0, height_mm=10.0
        ),
        _netlist("/XTAL1", "/VCC", "/ROW0"),
        route_ground_tracks=False,
        route_clock_before_power=True,
        route_power_before_matrix=True,
    )

    assert calls == [
        ("/XTAL1",),
        ("/VCC",),
        ("/ROW0",),
    ]


def test_clock_and_ground_precede_matrix_then_late_power_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def route_board(layout: BoardLayout, _netlist: BoardNetlist, **kwargs: object):
        calls.append(tuple(kwargs["net_order"]))  # type: ignore[arg-type]
        return SimpleNamespace(
            layout=layout,
            failed=(),
            run_result=SimpleNamespace(passes=()),
        )

    monkeypatch.setattr(retro_pad_board, "route_board", route_board)
    retro_pad_board.route_retro_pad_placement_layout(
        BoardLayout(
            placements=(), segments=(), vias=(), width_mm=10.0, height_mm=10.0
        ),
        _netlist("/XTAL1", "/GND", "/VCC", "/ROW0"),
        route_ground_before_matrix=True,
        route_clock_before_power=True,
        route_power_before_matrix=False,
    )

    assert calls == [
        ("/XTAL1",),
        ("/GND",),
        ("/ROW0",),
        ("/VCC",),
    ]
