from fastapi.routing import APIRoute

from app.main import app


PUBLIC_ROUTES = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/refresh"),
    ("GET", "/api/meta/features"),
}
COLLECTOR_AUTHENTICATED_ROUTES = {
    ("POST", "/api/projects/{project_id}/security/ingest"),
    ("POST", "/api/projects/{project_id}/security/build-snapshots/ingest"),
}
PROJECT_ROOT_ROUTES = {
    ("GET", "/api/projects/{project_id}"),
    ("PATCH", "/api/projects/{project_id}"),
    ("DELETE", "/api/projects/{project_id}"),
}


def _api_routes():
    for included in app.routes:
        router = getattr(included, "original_router", None)
        context = getattr(included, "include_context", None)
        if not router or not context:
            continue
        for route in router.routes:
            if isinstance(route, APIRoute):
                yield context.prefix + route.path, route


def _dependency_names(route: APIRoute) -> set[str]:
    names: set[str] = set()

    def walk(dependant) -> None:
        call = getattr(dependant, "call", None)
        if call:
            names.add(getattr(call, "__name__", type(call).__name__))
        for child in getattr(dependant, "dependencies", []):
            walk(child)

    walk(route.dependant)
    return names


def test_only_explicit_public_or_signed_collector_routes_lack_jwt_authentication():
    unauthenticated: set[tuple[str, str]] = set()
    mounted: set[tuple[str, str]] = set()
    for path, route in _api_routes():
        for method in route.methods:
            mounted.add((method, path))
            if "get_current_user" not in _dependency_names(route):
                unauthenticated.add((method, path))

    expected = PUBLIC_ROUTES | (COLLECTOR_AUTHENTICATED_ROUTES & mounted)
    assert unauthenticated == expected


def test_project_scoped_routes_enforce_project_or_assessment_access():
    missing_access_check: set[tuple[str, str]] = set()
    for path, route in _api_routes():
        if "/projects/{project_id}" not in path:
            continue
        dependency_names = _dependency_names(route)
        if dependency_names & {"require_project_access", "require_project_assessment_access"}:
            continue
        for method in route.methods:
            key = (method, path)
            if key not in PROJECT_ROOT_ROUTES | COLLECTOR_AUTHENTICATED_ROUTES:
                missing_access_check.add(key)

    assert not missing_access_check


def test_default_api_does_not_mount_experimental_capabilities():
    paths = set(app.openapi()["paths"])
    assert not any(path.startswith("/api/projects/{project_id}/security/") for path in paths)
    assert not any("/integrations" in path for path in paths)
