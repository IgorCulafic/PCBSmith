from __future__ import annotations

from pathlib import Path

from pcbsmith.evidence.models import CachedEvidenceFile, ComponentEvidence, EvidenceManifest


class EvidenceCache:
    def __init__(self, *, manifest_path: Path, manifest: EvidenceManifest) -> None:
        self._manifest_path = manifest_path.resolve()
        self._manifest = manifest

    @classmethod
    def from_manifest(cls, path: str | Path) -> EvidenceCache:
        manifest_path = Path(path)
        manifest = EvidenceManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        return cls(manifest_path=manifest_path, manifest=manifest)

    @property
    def manifest_path(self) -> Path:
        return self._manifest_path

    @property
    def components(self) -> tuple[ComponentEvidence, ...]:
        return self._manifest.components

    @property
    def cached_files(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        seen: set[Path] = set()
        for component in self.components:
            for cached_file in component.files:
                path = self.resolve_cached_file(cached_file)
                if path not in seen:
                    seen.add(path)
                    paths.append(path)
        return tuple(paths)

    def components_for_role(self, role: str) -> tuple[ComponentEvidence, ...]:
        return tuple(component for component in self.components if component.role == role)

    def first_component_for_role(self, role: str) -> ComponentEvidence | None:
        components = self.components_for_role(role)
        return components[0] if components else None

    def resolve_cached_file(self, cached_file: CachedEvidenceFile) -> Path:
        local_path = Path(cached_file.local_path)
        if local_path.is_absolute():
            return local_path
        return (self.manifest_path.parent / local_path).resolve()

    def missing_cached_files(self, component: ComponentEvidence) -> tuple[Path, ...]:
        return tuple(
            path
            for path in (self.resolve_cached_file(cached_file) for cached_file in component.files)
            if not path.exists()
        )

