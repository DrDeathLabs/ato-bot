from app.api.closure import _can_advance_artifact_approval
from app.core.rbac import Role


def test_control_owner_can_complete_owner_step_but_not_reviewer_or_isso_steps():
    assert _can_advance_artifact_approval("control_owner", Role.SYSTEM_OWNER)
    assert not _can_advance_artifact_approval("reviewer", Role.SYSTEM_OWNER)
    assert not _can_advance_artifact_approval("isso", Role.SYSTEM_OWNER)


def test_reviewer_and_assessor_cannot_impersonate_isso_approval():
    assert _can_advance_artifact_approval("reviewer", Role.REVIEWER)
    assert _can_advance_artifact_approval("reviewer", Role.ASSESSOR)
    assert not _can_advance_artifact_approval("isso", Role.REVIEWER)
    assert not _can_advance_artifact_approval("isso", Role.ASSESSOR)


def test_security_officer_and_admin_can_complete_isso_step():
    assert _can_advance_artifact_approval("isso", Role.SECURITY_OFFICER)
    assert _can_advance_artifact_approval("isso", Role.SYSTEM_ADMIN)
