from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolBox,
    QVBoxLayout,
    QWidget,
)

from pcbsmith.core.catalog import CatalogEntry, CatalogPreferences, CatalogSearchQuery
from pcbsmith.services import component_catalog

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
        self.family_box = QToolBox()
        self.component_list = QListWidget()
        self._visible_entry_ids: tuple[str, ...] = ()

        self.search_box.setPlaceholderText("Search components")

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
        while self.family_box.count():
            self.family_box.removeItem(0)

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

    def _populate_family_box(self, entries: list[CatalogEntry]) -> None:
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
            self.family_box.addItem(
                self._build_family_page(group_entries),
                group.name,
            )

    def _build_family_page(self, entries: list[CatalogEntry]) -> QWidget:
        page = QWidget()
        grid = QGridLayout()
        for index, entry in enumerate(entries):
            button = QPushButton(entry.family.name)
            button.setToolTip(entry.variant.name)
            button.setProperty(BUTTON_ENTRY_ID_PROPERTY, entry.id)
            button.clicked.connect(
                lambda _checked=False, entry_id=entry.id: self.entry_activated.emit(
                    entry_id
                )
            )
            grid.addWidget(button, index // 3, index % 3)
        page.setLayout(grid)
        return page

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
