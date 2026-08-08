"""System Profile service — derives N/A control applicability from system characteristics."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import SystemProfile


def derive_na_controls(profile: SystemProfile, controls: list) -> dict[str, str]:
    """
    Returns dict of control_id -> rationale for controls that are N/A
    based on the system profile. Only returns controls that are N/A;
    absence means applicable.
    """
    na: dict[str, str] = {}

    def add_family(family: str, rationale: str) -> None:
        for c in controls:
            if c.family_id.upper() == family:
                na[c.display_id] = rationale

    def add_prefix(prefix: str, rationale: str) -> None:
        """Add a base control and all its enhancements."""
        for c in controls:
            cid = c.display_id
            if cid == prefix or cid.startswith(f"{prefix}("):
                na[cid] = rationale

    # ── Physical / Environmental ──────────────────────────────────────────────
    if not profile.has_physical_facilities:
        add_family(
            "PE",
            "No physical facilities in system boundary; physical/environmental "
            "controls not applicable.",
        )
        # Physical maintenance (MA-2, MA-3, MA-5, MA-6 — not MA-1 policy or MA-4 remote)
        for pfx in ("MA-2", "MA-3", "MA-5", "MA-6"):
            add_prefix(
                pfx,
                "No physical facilities; hardware maintenance controls not applicable.",
            )

    # ── Media Protection — physical media ────────────────────────────────────
    if not profile.has_physical_facilities and not profile.has_removable_media:
        for pfx in ("MP-2", "MP-3", "MP-4", "MP-6", "MP-7"):
            add_prefix(
                pfx,
                "No physical facilities or removable media in system boundary.",
            )

    if not profile.has_removable_media:
        add_prefix(
            "MP-5",
            "No removable/portable media in system boundary.",
        )

    # ── Wireless ─────────────────────────────────────────────────────────────
    if not profile.has_wireless_networking:
        add_prefix(
            "AC-18",
            "System does not use wireless networking.",
        )

    # ── Mobile devices ───────────────────────────────────────────────────────
    if not profile.has_mobile_devices:
        add_prefix(
            "AC-19",
            "No mobile devices in system boundary.",
        )

    # ── External / non-org users ─────────────────────────────────────────────
    if profile.user_population == "internal_only":
        add_prefix(
            "IA-8",
            "System serves internal organizational users only; external user "
            "identification and authentication not applicable.",
        )

    return na


async def get_profile(project_id: int, db: AsyncSession) -> SystemProfile | None:
    result = await db.execute(
        select(SystemProfile).where(SystemProfile.project_id == project_id)
    )
    return result.scalar_one_or_none()


async def get_na_map(project_id: int, db: AsyncSession, controls: list) -> dict[str, str]:
    """Returns N/A map for project, or empty dict if no profile set."""
    profile = await get_profile(project_id, db)
    if not profile:
        return {}
    return derive_na_controls(profile, controls)
