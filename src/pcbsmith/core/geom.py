from __future__ import annotations

from pydantic import BaseModel, ConfigDict

NM_PER_MM = 1_000_000


def mm_to_nm(value: float) -> int:
    return int(value * NM_PER_MM + (0.5 if value >= 0 else -0.5))


def nm_to_mm(value: int) -> float:
    return value / NM_PER_MM


class Vec(BaseModel):
    model_config = ConfigDict(frozen=True)

    dx: int
    dy: int

    def __init__(self, dx: int, dy: int) -> None:
        super().__init__(dx=dx, dy=dy)


class Point(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: int
    y: int

    def __init__(self, x: int, y: int) -> None:
        super().__init__(x=x, y=y)

    @classmethod
    def from_mm(cls, x: float, y: float) -> Point:
        return cls(x=mm_to_nm(x), y=mm_to_nm(y))

    def __add__(self, vector: Vec) -> Point:
        return Point(x=self.x + vector.dx, y=self.y + vector.dy)

    def __sub__(self, other: Point) -> Vec:
        return Vec(dx=self.x - other.x, dy=self.y - other.y)


class Box(BaseModel):
    model_config = ConfigDict(frozen=True)

    left: int
    top: int
    right: int
    bottom: int

    def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
        super().__init__(left=left, top=top, right=right, bottom=bottom)

    def contains(self, point: Point) -> bool:
        return self.left <= point.x <= self.right and self.top <= point.y <= self.bottom

    def intersects(self, other: Box) -> bool:
        return not (
            self.right < other.left
            or other.right < self.left
            or self.bottom < other.top
            or other.bottom < self.top
        )


def snap(point: Point, grid_nm: int) -> Point:
    if grid_nm <= 0:
        raise ValueError("grid_nm must be positive")
    return Point(
        x=round(point.x / grid_nm) * grid_nm,
        y=round(point.y / grid_nm) * grid_nm,
    )
