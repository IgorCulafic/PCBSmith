"""Read native copper declarations by name, independent of KiCad numeric IDs."""

from pcbsmith.copper_layers import ordered_copper_layers
from pcbsmith.kicad.library import SList, _atom, _children


def saved_copper_layers(root: SList) -> tuple[str, ...]:
    tables = _children(root, "layers")
    if len(tables) != 1:
        raise ValueError("native board requires one explicit copper layer table")
    names = tuple(
        _atom(row[1])
        for row in tables[0][1:]
        if isinstance(row, list) and len(row) >= 3 and _atom(row[1]).endswith(".Cu")
    )
    ordered = ordered_copper_layers(names)
    if names != ordered or len(names) < 2:
        raise ValueError("native copper layer table is not in physical stack order")
    return ordered
