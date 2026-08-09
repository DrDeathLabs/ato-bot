from app.models.schemas import ProjectCreate, ProjectResponse, ProjectUpdate


def test_project_create_exposes_optional_system_owner_assignment():
    project = ProjectCreate(name="System", system_owner_id=42)
    assert project.system_owner_id == 42


def test_project_update_can_clear_system_owner_assignment():
    project = ProjectUpdate(system_owner_id=None)
    assert project.model_dump(exclude_unset=True) == {"system_owner_id": None}


def test_project_response_exposes_system_owner_id():
    fields = ProjectResponse.model_fields
    assert "system_owner_id" in fields
