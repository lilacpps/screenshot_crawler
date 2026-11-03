"""Read-only complete-listing DTOs shared by GUI and site adapters."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class ListingRow:
    """One site-native row observed in a complete listing."""

    external_id: str
    url: str
    site_position: int
    display_title: str
    access_observation: str
    listing_identity: str


@dataclass(frozen=True, slots=True)
class NativeListingProof:
    """Complete site-declared ID/order projection, independent of GUI rows.

    Only adapters validating the declared total and full native arrays may
    supply this proof. Missing ordinals have no inferred episode identity.
    """

    declared_count: int
    ordered_positions: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class ListingPreview:
    """Read-only listing result; it has no Catalog or Watchlist side effects."""

    site: str
    target_key: str
    target_url: str
    listing_identity: str | None
    rows: tuple[ListingRow, ...]
    complete: bool
    observed_at: datetime
    digest: str | None
    blockers: tuple[str, ...] = ()
    native_order: NativeListingProof | None = None
    supports_exclusions: bool = True

    @property
    def ready(self) -> bool:
        return self.complete and self.digest is not None and not self.blockers


def listing_digest(
    listing_identity: str, rows: tuple[ListingRow, ...], *,
    native_order: NativeListingProof | None = None, supports_exclusions: bool = True,
) -> str:
    """Hash only stable listing identity, IDs, and authoritative positions."""

    payload = {
        "listing_identity": listing_identity,
        "rows": [
            {
                "external_id": row.external_id,
                "site_position": row.site_position,
            }
            for row in rows
        ],
    }
    # Preserve existing adapters' digests. Opt-in native proofs and restricted
    # selections are explicitly bound; changing either invalidates the proof.
    if native_order is not None or not supports_exclusions:
        payload["native_order"] = None if native_order is None else {
            "declared_count": native_order.declared_count,
            "ordered_positions": native_order.ordered_positions,
        }
        payload["supports_exclusions"] = supports_exclusions
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def blocked_listing_preview(
    *, site: str, target_key: str, target_url: str, reason: str
) -> ListingPreview:
    """Build a visible blocker for adapters without the optional capability."""

    return ListingPreview(
        site=site,
        target_key=target_key,
        target_url=target_url,
        listing_identity=None,
        rows=(),
        complete=False,
        observed_at=datetime.now(UTC),
        digest=None,
        blockers=(reason,),
    )
