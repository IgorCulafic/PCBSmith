from __future__ import annotations

import pytest

from pcbsmith.ui.selection import SelectionKey, parse_index_key


def test_parse_index_key_accepts_non_negative_integer_strings() -> None:
    assert parse_index_key(SelectionKey("wire", "0")) == 0


def test_parse_index_key_rejects_non_integer_keys() -> None:
    with pytest.raises(ValueError, match="Invalid wire key"):
        parse_index_key(SelectionKey("wire", "abc"))
