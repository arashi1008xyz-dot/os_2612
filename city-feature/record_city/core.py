"""Amount-only interface. No record database, routes, session state, or I/O."""
from dataclasses import dataclass, fields
from decimal import Decimal, localcontext
from typing import Mapping
from .config import CityConfig, load_config, number


@dataclass(frozen=True)
class RecordAmounts:
    book_pages: Decimal = Decimal(0)
    manga_pages: Decimal = Decimal(0)
    anime_minutes: Decimal = Decimal(0)
    movie_minutes: Decimal = Decimal(0)
    drama_minutes: Decimal = Decimal(0)

    def __post_init__(self):
        for field in fields(self):
            object.__setattr__(self, field.name, number(getattr(self, field.name), field.name))

    @classmethod
    def from_mapping(cls, amounts: Mapping):
        if not isinstance(amounts, Mapping):
            raise ValueError("Amounts must be an object with named quantity fields")
        unknown = set(amounts) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown amount keys: {sorted(unknown)}")
        return cls(**amounts)


STAGE_LABELS = {"empty": "更地", "groundwork": "基礎工事中", "foundation": "基礎完成",
                "frame": "骨組み完成", "shell": "外装完成", "complete": "街が完成しました"}


@dataclass(frozen=True)
class CityState:
    total_minutes: Decimal
    displayed_minutes: Decimal
    completed_total: int
    completed_visible: int
    max_buildings: int
    stage: str
    progress: Decimal
    remaining_minutes: Decimal
    current_building: int | None
    capped: bool
    plan_version: str

    @property
    def stage_label(self):
        return STAGE_LABELS[self.stage]

    def to_dict(self):
        """Decimals are exact JSON strings; counts are integers, flags booleans."""
        return {f.name: str(value) if isinstance(value := getattr(self, f.name), Decimal) else value
                for f in fields(self)}


def calculate_city(amounts: RecordAmounts | Mapping, config: CityConfig | None = None):
    if not isinstance(amounts, RecordAmounts):
        amounts = RecordAmounts.from_mapping(amounts)
    config = config or load_config()
    # Adapt precision to inputs, including tiny fractions and very large totals.
    values = [getattr(amounts, key) for key in config.rates] + list(config.rates.values())
    precision = max(28, 2 * (max(v.adjusted() for v in values)
                           - min(v.as_tuple().exponent for v in values) + 10))
    with localcontext() as context:
        context.prec = precision
        total = sum((getattr(amounts, key) * rate for key, rate in config.rates.items()), Decimal(0))
        limit = config.minutes_per_building * config.max_buildings
        visible = min(total, limit)
        completed = int(total // config.minutes_per_building)
        if total >= limit:
            return CityState(total, visible, completed, config.max_buildings, config.max_buildings,
                             "complete", Decimal(1), Decimal(0), None, True, config.plan_version)
        remainder = total % config.minutes_per_building
        ratio = remainder / config.minutes_per_building
        stage = ("empty" if remainder == 0 else "groundwork" if ratio < Decimal(".25")
                 else "foundation" if ratio < Decimal(".5") else "frame" if ratio < Decimal(".75") else "shell")
        return CityState(total, visible, completed, completed, config.max_buildings, stage, ratio,
                         config.minutes_per_building - remainder, completed + 1, False, config.plan_version)
