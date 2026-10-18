"""Load immutable conversion rules and the complete, versioned 120-building plan."""
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

AMOUNT_KEYS = ("book_pages", "manga_pages", "anime_minutes", "movie_minutes", "drama_minutes")
DATA = Path(__file__).with_name("data")


def number(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{label}: a finite nonnegative number is required")
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError(f"{label}: a finite {'positive' if positive else 'nonnegative'} number is required")
    return result


def read_json(path):
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON number: {value}")
    with Path(path).open(encoding="utf-8-sig") as handle:
        return json.load(handle, parse_float=Decimal, parse_constant=reject_constant)


@dataclass(frozen=True)
class Volume:
    x: float
    y: float
    width: float
    depth: float
    z: float
    height: float
    bands: bool


@dataclass(frozen=True)
class Building:
    id: int
    block: int
    style: str
    palette: str
    x: float
    y: float
    width: float
    depth: float
    height: float
    volumes: tuple[Volume, ...]


@dataclass(frozen=True)
class Block:
    id: int
    x: float
    y: float
    width: float
    depth: float


@dataclass(frozen=True)
class CityConfig:
    rates: Mapping[str, Decimal]
    minutes_per_building: Decimal
    max_buildings: int
    plan_version: str
    buildings: tuple[Building, ...]
    blocks: tuple[Block, ...]
    palettes: Mapping[str, tuple[str, ...]]


def load_config(rules_path=None, layout_path=None):
    """Bad/missing files raise; defaults are never silently substituted or saved."""
    rules = read_json(rules_path or DATA / "rules.json")
    layout = read_json(layout_path or DATA / "city_layout.json")
    if not isinstance(rules, dict) or not isinstance(layout, dict):
        raise ValueError("City JSON roots must be objects")
    if rules.get("schema_version") != 1 or layout.get("schema_version") != 1:
        raise ValueError("Unsupported city JSON schema_version")
    if set(rules["minutes_per_unit"]) != set(AMOUNT_KEYS):
        raise ValueError("Conversion rules must contain exactly the five amount keys")
    rates = {key: number(rules["minutes_per_unit"][key], key, positive=True) for key in AMOUNT_KEYS}
    per_building = number(rules["minutes_per_building"], "minutes_per_building", positive=True)
    maximum = rules["max_buildings"]
    if type(maximum) is not int or not 1 <= maximum <= 120:
        raise ValueError("max_buildings must be an integer from 1 to 120")
    palettes = {}
    for key, colors in layout["palettes"].items():
        if not re.fullmatch(r"[a-z]+", key):
            raise ValueError("Palette names must be lowercase ASCII letters")
        if len(colors) != 3 or not all(isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in colors):
            raise ValueError("Each palette must have three hex colors")
        palettes[key] = tuple(colors)
    blocks = []
    for raw in layout["blocks"]:
        if type(raw["id"]) is not int or raw["id"] < 1:
            raise ValueError("Block IDs must be positive integers")
        dims = {k: float(number(raw[k], f"block.{k}", positive=k in ("width", "depth")))
                for k in ("x", "y", "width", "depth")}
        if dims["x"]+dims["width"]>448 or dims["y"]+dims["depth"]>362:
            raise ValueError("Block geometry exceeds the fixed camera")
        blocks.append(Block(id=raw["id"], **dims))
    if len({b.id for b in blocks}) != len(blocks):
        raise ValueError("Block IDs must be unique")
    block_map = {b.id: b for b in blocks}
    buildings = []
    for index, raw in enumerate(layout["buildings"], 1):
        if type(raw["id"]) is not int or raw["id"] != index:
            raise ValueError("Building IDs must be consecutive in growth order")
        if raw["palette"] not in palettes or raw["block"] not in block_map:
            raise ValueError("Unknown palette or block")
        dims = {k: float(number(raw[k], f"building.{k}", positive=k in ("width", "depth", "height")))
                for k in ("x", "y", "width", "depth", "height")}
        if dims["height"]>300 or not 1<=len(raw["volumes"])<=8:
            raise ValueError("Building height or volume count exceeds the supported plan")
        block = block_map[raw["block"]]
        if (dims["x"] < block.x - 1e-6 or dims["y"] < block.y - 1e-6
                or dims["x"] + dims["width"] > block.x + block.width + 1e-6
                or dims["y"] + dims["depth"] > block.y + block.depth + 1e-6):
            raise ValueError("Building lies outside its block")
        volumes = []
        for v in raw["volumes"]:
            shape = {k: float(number(v[k], f"volume.{k}", positive=k in ("width", "depth", "height")))
                     for k in ("x", "y", "width", "depth", "z", "height")}
            if (shape["x"] + shape["width"] > dims["width"] + 1e-4
                    or shape["y"] + shape["depth"] > dims["depth"] + 1e-4
                    or shape["z"] + shape["height"] > dims["height"] + 1e-4):
                raise ValueError("Volume lies outside its building")
            if type(v["bands"]) is not bool:
                raise ValueError("Volume bands must be boolean")
            volumes.append(Volume(**shape, bands=v["bands"]))
        if not volumes:
            raise ValueError("Buildings need at least one volume")
        buildings.append(Building(id=index, block=raw["block"], style=raw["style"],
                                  palette=raw["palette"], volumes=tuple(volumes), **dims))
    if len(buildings) != 120:
        raise ValueError("The master plan must contain exactly 120 buildings")
    return CityConfig(MappingProxyType(rates), per_building, maximum, str(layout["plan_version"]),
                      tuple(buildings), tuple(blocks), MappingProxyType(palettes))
