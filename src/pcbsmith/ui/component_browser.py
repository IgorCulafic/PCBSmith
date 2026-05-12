from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pcbsmith.core.catalog import CatalogEntry, CatalogPreferences, CatalogSearchQuery
from pcbsmith.services import component_catalog
from pcbsmith.ui.icons import symbol_icon

ENTRY_ID_ROLE = Qt.ItemDataRole.UserRole
BUTTON_ENTRY_ID_PROPERTY = "catalogEntryId"


class ComponentBrowser(QWidget):
    entry_activated = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.catalog = component_catalog.builtin_catalog()
        self.project_preferences = CatalogPreferences()
        self.search_box = QLineEdit()
        self.preferred_only = QCheckBox("Preferred")
        self.family_box = QWidget()
        self.family_layout = QVBoxLayout()
        self.component_list = QListWidget()
        self._visible_entry_ids: tuple[str, ...] = ()
        self._family_headers: dict[str, QToolButton] = {}
        self._family_pages: dict[str, QWidget] = {}

        self.search_box.setPlaceholderText("Search components")
        self.family_layout.setContentsMargins(0, 0, 0, 0)
        self.family_layout.setSpacing(4)
        self.family_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.family_box.setLayout(self.family_layout)

        layout = QVBoxLayout()
        layout.addWidget(self.search_box)
        layout.addWidget(self.preferred_only)
        layout.addWidget(self.family_box)
        layout.addWidget(self.component_list)
        self.setLayout(layout)

        self.search_box.textChanged.connect(self.refresh)
        self.preferred_only.toggled.connect(self.refresh)
        self.component_list.itemDoubleClicked.connect(self._emit_entry_activated)
        self.refresh()

    def refresh(self) -> None:
        self.component_list.clear()
        self._clear_family_box()

        query = CatalogSearchQuery(
            text=self.search_box.text(),
            preferred_only=self.preferred_only.isChecked(),
        )
        entries = component_catalog.search_catalog(
            self.catalog,
            query,
            project_preferences=self.project_preferences,
        )

        self._visible_entry_ids = tuple(entry.id for entry in entries)
        if not self.search_box.text().strip():
            self.component_list.hide()
            self.family_box.show()
            self._populate_family_box(entries)
            return

        self.family_box.hide()
        self.component_list.show()
        for entry in entries:
            item = QListWidgetItem(entry.variant.name)
            item.setData(ENTRY_ID_ROLE, entry.id)
            self.component_list.addItem(item)

    def _populate_family_box(self, entries: tuple[CatalogEntry, ...]) -> None:
        entries_by_group: dict[str, list[CatalogEntry]] = {
            group.id: [] for group in self.catalog.groups
        }
        for entry in entries:
            for group_id in entry.group_ids:
                if group_id in entries_by_group:
                    entries_by_group[group_id].append(entry)

        for group in self.catalog.groups:
            group_entries = entries_by_group[group.id]
            if not group_entries:
                continue
            self._add_family(group.name, self._build_family_page(group_entries))

    def _clear_family_box(self) -> None:
        self._family_headers.clear()
        self._family_pages.clear()
        while self.family_layout.count():
            item = self.family_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _add_family(self, title: str, page: QWidget) -> None:
        header = QToolButton()
        header.setText(title)
        header.setCheckable(True)
        header.setChecked(True)
        header.setArrowType(Qt.ArrowType.DownArrow)
        header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        header.clicked.connect(
            lambda checked=False, header=header, page=page: self._set_family_open(
                header, page, checked
            )
        )
        self._family_headers[title] = header
        self._family_pages[title] = page
        self.family_layout.addWidget(header)
        self.family_layout.addWidget(page)

    def _build_family_page(self, entries: list[CatalogEntry]) -> QWidget:
        page = QWidget()
        grid = QGridLayout()
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, entry in enumerate(entries):
            button = QPushButton(self._family_button_text(entry))
            button.setIcon(symbol_icon(entry.symbol_id))
            button.setIconSize(QSize(32, 24))
            button.setMaximumHeight(36)
            button.setMinimumHeight(28)
            button.setToolTip(self._entry_tooltip(entry))
            button.setProperty(BUTTON_ENTRY_ID_PROPERTY, entry.id)
            button.clicked.connect(
                lambda _checked=False, entry_id=entry.id: self.entry_activated.emit(entry_id)
            )
            grid.addWidget(button, index // 3, index % 3)
        page.setLayout(grid)
        return page

    def _set_family_open(
        self,
        header: QToolButton,
        page: QWidget,
        open_: bool,
    ) -> None:
        page.setVisible(open_)
        header.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)

    def _family_button_text(self, entry: CatalogEntry) -> str:
        if entry.symbol_id in {"stdlib:VCC", "stdlib:GND"}:
            return entry.variant.name
        return entry.family.name

    def _entry_tooltip(self, entry: CatalogEntry) -> str:
        shortcuts = {
            "pcbs:resistor_0603": "R",
            "pcbs:capacitor_0603": "C",
            "pcbs:diode_0603": "D",
            "pcbs:led_0603": "L",
        }
        shortcut = shortcuts.get(entry.id)
        if shortcut is None:
            return entry.variant.name
        return f"{entry.variant.name} ({shortcut})"

    def family_titles(self) -> tuple[str, ...]:
        return tuple(self._family_headers)

    def family_header(self, title: str) -> QToolButton:
        return self._family_headers[title]

    def family_page(self, title: str) -> QWidget:
        return self._family_pages[title]

    def set_project_preferences(
        self,
        *,
        enabled_group_ids: tuple[str, ...] = (),
        visible_entry_ids: tuple[str, ...] = (),
        hidden_entry_ids: tuple[str, ...] = (),
    ) -> None:
        self.project_preferences = CatalogPreferences(
            enabled_group_ids=enabled_group_ids,
            visible_entry_ids=visible_entry_ids,
            hidden_entry_ids=hidden_entry_ids,
        )
        self.refresh()

    def visible_entry_ids(self) -> tuple[str, ...]:
        return self._visible_entry_ids

    def select_entry(self, entry_id: str) -> None:
        if entry_id not in self._visible_entry_ids:
            raise ValueError(f"Catalog entry is not visible: {entry_id}")

        for index in range(self.component_list.count()):
            item = self.component_list.item(index)
            if item.data(ENTRY_ID_ROLE) == entry_id:
                self.component_list.setCurrentItem(item)
                return

    def selected_entry(self) -> CatalogEntry | None:
        item = self.component_list.currentItem()
        if item is None:
            return None
        return component_catalog.entry_by_id(self.catalog, item.data(ENTRY_ID_ROLE))

    def _emit_entry_activated(self, item: QListWidgetItem) -> None:
        self.entry_activated.emit(item.data(ENTRY_ID_ROLE))
