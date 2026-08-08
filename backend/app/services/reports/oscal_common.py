"""Shared helpers for OSCAL exports."""
from __future__ import annotations

import mimetypes
import re
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from app.core.config import get_settings
from app.models.orm import Document, User
from app.services.controls.catalog import load_catalog

settings = get_settings()
OSCAL_NAMESPACE = settings.oscal_namespace


def stable_uuid(*parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, "::".join(str(part) for part in parts)))


def iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def prop(name: str, value: object, *, ns: str = OSCAL_NAMESPACE) -> dict:
    return {"name": name, "value": str(value), "ns": ns}


def oscal_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]", "-", value or "")
    token = token.strip("-")
    if not token:
        token = "item"
    if not re.match(r"^[A-Za-z_]", token):
        token = f"item-{token}"
    return token


def catalog_id(display_id: str) -> str:
    catalog = load_catalog()
    for control in catalog.values():
        if control.display_id.upper() == display_id.upper():
            return control.id
    return oscal_token(display_id.lower())


def _absolute_url(base: str, path: str) -> str:
    if path.startswith(("http://", "https://", "urn:")):
        return path
    base = base.rstrip("/")
    path = path if path.startswith("/") else f"/{path}"
    return f"{base}{path}"


def api_url(path: str) -> str:
    return _absolute_url(settings.api_base_url, path)


def frontend_url(path: str) -> str:
    return _absolute_url(settings.frontend_base_url, path)


def nist_baseline_profile_url(baseline: str) -> str:
    baseline_name = (baseline or "moderate").upper()
    return (
        "https://raw.githubusercontent.com/usnistgov/oscal-content/main/"
        f"nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_{baseline_name}-baseline_profile.json"
    )


def link(href: str, *, rel: str | None = None, text: str | None = None, media_type: str | None = None) -> dict:
    entry = {"href": href}
    if rel:
        entry["rel"] = rel
    if text:
        entry["text"] = text
    if media_type:
        entry["media-type"] = media_type
    return entry


def party_uuid(kind: str, value: object) -> str:
    return stable_uuid("oscal-party", kind, value)


def default_roles(*, artifact_name: str) -> list[dict]:
    return [
        {
            "id": "system-owner",
            "title": "System Owner",
            "short-name": "Owner",
            "description": "Responsible for the assessed system and its formal authorization artifacts.",
        },
        {
            "id": "assessor",
            "title": "Assessor",
            "short-name": "Assessor",
            "description": "Performed the assessment and reviewed supporting evidence.",
        },
        {
            "id": "assessment-platform",
            "title": "Assessment Platform",
            "short-name": "Platform",
            "description": f"Assessment platform that generated this OSCAL {artifact_name} export.",
        },
    ]


def organization_party() -> tuple[str, dict]:
    org_uuid = party_uuid("organization", "ato-bot")
    return org_uuid, {
        "uuid": org_uuid,
        "type": "organization",
        "name": "ATO Bot",
        "short-name": "ATO Bot",
        "props": [
            prop("platform", "ato-bot"),
            prop("role", "assessment-platform"),
        ],
        "links": [
            link(frontend_url("/projects"), rel="homepage", text="ATO Bot projects"),
        ],
    }


def person_party(user: User, *, org_uuid: str, role_name: str) -> dict:
    party = {
        "uuid": party_uuid("user", user.id),
        "type": "person",
        "name": user.username,
        "short-name": user.username,
        "props": [
            prop("user-id", user.id),
            prop("username", user.username),
            prop("application-role", user.role),
            prop("oscal-role", role_name),
        ],
        "member-of-organizations": [org_uuid],
    }
    if user.email:
        party["email-addresses"] = [user.email]
    return party


def responsible_party(role_id: str, *party_uuids: str) -> dict:
    return {
        "role-id": role_id,
        "party-uuids": list(dict.fromkeys(party_uuids)),
    }


def build_metadata_identities(*, owner: User | None, assessor: User | None, artifact_name: str) -> tuple[str, list[dict], list[dict], list[dict]]:
    org_uuid, org_party = organization_party()
    parties = [org_party]
    responsible_parties = [responsible_party("assessment-platform", org_uuid)]
    if owner:
        owner_party = person_party(owner, org_uuid=org_uuid, role_name="system-owner")
        parties.append(owner_party)
        responsible_parties.append(responsible_party("system-owner", owner_party["uuid"]))
    if assessor:
        assessor_party = person_party(assessor, org_uuid=org_uuid, role_name="assessor")
        if not any(p["uuid"] == assessor_party["uuid"] for p in parties):
            parties.append(assessor_party)
        responsible_parties.append(responsible_party("assessor", assessor_party["uuid"]))
    return org_uuid, default_roles(artifact_name=artifact_name), parties, responsible_parties


def actor_origin(org_uuid: str) -> list[dict]:
    return [{"actors": [{"type": "assessment-platform", "actor-uuid": org_uuid}]}]


def document_download_href(document: Document) -> str:
    if document.project_id:
        return api_url(f"/api/projects/{document.project_id}/documents/{document.id}/download")
    if getattr(document, "provider_id", None):
        return api_url(f"/api/common-controls/providers/{document.provider_id}/documents/{document.id}/download")
    if getattr(document, "policy_library_id", None):
        return api_url(f"/api/enterprise-policies/libraries/{document.policy_library_id}/documents/{document.id}/download")
    if getattr(document, "procedure_library_id", None):
        return api_url(f"/api/enterprise-procedures/libraries/{document.procedure_library_id}/documents/{document.id}/download")
    return f"urn:ato-bot:document:{document.id}"


def guess_media_type(document: Document) -> str:
    if document.file_type and "/" in document.file_type:
        return document.file_type
    guessed, _ = mimetypes.guess_type(document.filename)
    if guessed:
        return guessed
    mapping = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "json": "application/json",
        "txt": "text/plain",
        "md": "text/markdown",
        "csv": "text/csv",
    }
    return mapping.get((document.file_type or "").lower(), "application/octet-stream")


def resource_entry(document: Document, *, description: str) -> dict:
    resource_uuid = stable_uuid("document-resource", document.id)
    props = [
        prop("document-id", document.id),
        prop("filename", document.filename),
        prop("file-hash", document.file_hash),
        prop("file-type", document.file_type),
        prop("parse-status", document.parse_status),
        prop("scope", "project" if document.project_id else "library"),
        prop("file-size-bytes", document.file_size_bytes),
        prop("created-at", iso(document.created_at) or ""),
        prop("uploaded-by", document.uploaded_by),
    ]
    if document.page_count is not None:
        props.append(prop("page-count", document.page_count))

    return {
        "uuid": resource_uuid,
        "title": document.filename,
        "description": description,
        "document-ids": [
            {
                "scheme": "urn:ato-bot:document-id",
                "identifier": str(document.id),
            }
        ],
        "citation": {
            "text": (
                f"{document.filename} | type={document.file_type} | "
                f"parse-status={document.parse_status} | sha256={document.file_hash}"
            ),
            "links": [
                link(document_download_href(document), rel="reference", text="Evidence download"),
            ],
        },
        "props": props,
        "rlinks": [
            {
                "href": document_download_href(document),
                "media-type": guess_media_type(document),
                "hashes": [
                    {
                        "algorithm": "SHA-256",
                        "value": document.file_hash,
                    }
                ],
            }
        ],
        "remarks": "Stored evidence resource referenced by this OSCAL artifact.",
    }


def first_non_empty(values: Iterable[str | None], fallback: str) -> str:
    for value in values:
        if value and str(value).strip():
            return str(value)
    return fallback
