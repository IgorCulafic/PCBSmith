from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pcbsmith.core.catalog import CatalogEntry, CatalogPreferences, CatalogSearchQuery
from pcbsmith.services import component_catalog

ENTRY_ID_ROLE = Qt.ItemDataRole.UserRole


class ComponentBrowser(QWidget):
    entry_activated = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.catalog = component_catalog.builtin_catalog()
        self.project_preferences = CatalogPreferences()
        self.search_box = QLineEdit()
        self.preferred_only = QCheckBox("Preferred")
        self.component_list = QListWidget()

        self.search_box.setPlaceholderText("Search components")

        layout = QVBoxLayout()
        layout.addWidget(self.search_box)
        layout.addWidget(self.preferred_only)
        layout.addWidget(self.component_list)
        self.setLayout(layout)

        self.search_box.textChanged.connect(self.refresh)
        self.preferred_only.toggled.connect(self.refresh)
        self.component_list.itemDoubleClicked.connect(self._emit_entry_activated)
        self.refresh()

    def refresh(self) -> None:
        self.component_list.clear()
        query = CatalogSearchQuery(
            text=self.search_box.text(),
            preferred_only=self.preferred_only.isChecked(),
        )
        entries = component_catalog.search_catalog(
            self.catalog,
            query,
            project_preferences=self.project_preferences,
        )
        for entry in entries:
            item = QListWidgetItem(entry.variant.name)
            item.setData(ENTRY_ID_ROLE, entry.id)
            self.component_list.addItem(item)

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
        return tuple(
            self.component_list.item(index).data(ENTRY_ID_ROLE)
            for index in range(self.component_list.count())
        )

    def select_entry(self, entry_id: str) -> None:
        for index in range(self.component_list.count()):
            item = self.component_list.item(index)
            if item.data(ENTRY_ID_ROLE) == entry_id:
                self.component_list.setCurrentItem(item)
                return
        raise ValueError(f"Catalog entry is not visible: {entry_id}")

    def selected_entry(self) -> CatalogEntry | None:
        item = self.component_list.currentItem()
        if item is None:
            return None
        return component_catalog.entry_by_id(self.catalog, item.data(ENTRY_ID_ROLE))

    def _emit_entry_activated(self, item: QListWidgetItem) -> None:
        self.entry_activated.emit(item.data(ENTRY_ID_ROLE))
