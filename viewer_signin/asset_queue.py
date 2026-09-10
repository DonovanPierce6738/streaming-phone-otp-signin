"""Creator uploads: ingest -> processing -> delivered, one transition at a time."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Literal

AssetState = Literal["ingested", "processing", "delivered"]


@dataclass
class Asset:
    asset_id: str
    creator_phone: str
    title: str
    source_key: str
    renditions: tuple[str, ...]
    state: AssetState = "ingested"
    delivered: list[str] = field(default_factory=list)


class AssetQueue:
    def __init__(self) -> None:
        self._assets: dict[str, Asset] = {}
        self._by_source: dict[tuple[str, str], str] = {}
        self._ids = itertools.count(1)

    def ingest(self, creator_phone: str, title: str, source_key: str, renditions: tuple[str, ...]) -> Asset:
        # source_key is the creator-supplied id, so a retried upload lands on the same asset.
        key = (creator_phone, source_key)
        if key in self._by_source:
            return self._assets[self._by_source[key]]
        asset_id = f"ast_{next(self._ids):04d}"
        asset = Asset(
            asset_id=asset_id,
            creator_phone=creator_phone,
            title=title,
            source_key=source_key,
            renditions=renditions,
        )
        self._assets[asset_id] = asset
        self._by_source[key] = asset_id
        return asset

    def run_next_job(self) -> Asset | None:
        for asset in self._assets.values():
            if asset.state == "ingested":
                asset.state = "processing"
                asset.delivered = [f"{asset.asset_id}/{r}.m3u8" for r in asset.renditions]
                asset.state = "delivered"
                return asset
        return None

    def get(self, asset_id: str) -> Asset | None:
        return self._assets.get(asset_id)
