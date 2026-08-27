from tests.conftest import auth_headers


def _create_skill(client, user, name="Estimate Generator"):
    resp = client.post(
        "/skills",
        json={
            "name": name,
            "department": "operations",
            "instructions": "Generate cost estimates from project scope.",
            "requested_tools": ["generate_report"],
        },
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _submit_and_approve(client, owner, skill_id, version_id, submitter=None):
    """Helper: run a version through submit-for-review -> owner approve."""
    submitter = submitter or owner
    resp = client.post(
        f"/skills/{skill_id}/versions/{version_id}/submit-for-review",
        headers=auth_headers(submitter),
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"/skills/{skill_id}/versions/{version_id}/approve",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_full_lifecycle_draft_review_approve_activate(client, orgs):
    abc = orgs["abc"]
    skill = _create_skill(client, abc.owner)
    assert skill["status"] == "draft"
    version_id = skill["versions"][0]["id"]
    assert skill["versions"][0]["status"] == "draft"

    resp = client.get("/departments/operations/active-skills", headers=auth_headers(abc.owner))
    assert resp.json() == []

    # A draft version cannot be activated directly - it must go through review/approval.
    resp = client.post(
        f"/skills/{skill['id']}/versions/{version_id}/activate",
        headers=auth_headers(abc.owner),
    )
    assert resp.status_code == 409
    assert "approved" in resp.json()["detail"].lower()

    approved = _submit_and_approve(client, abc.owner, skill["id"], version_id)
    assert approved["status"] == "approved"
    assert approved["reviewed_by"] == abc.owner.id

    # An in_review (not yet approved) version also cannot activate.
    skill2 = _create_skill(client, abc.owner, name="Second Skill")
    v2 = skill2["versions"][0]["id"]
    client.post(f"/skills/{skill2['id']}/versions/{v2}/submit-for-review", headers=auth_headers(abc.owner))
    resp = client.post(f"/skills/{skill2['id']}/versions/{v2}/activate", headers=auth_headers(abc.owner))
    assert resp.status_code == 409

    resp = client.post(
        f"/skills/{skill['id']}/versions/{version_id}/activate",
        headers=auth_headers(abc.owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"

    resp = client.get(f"/skills/{skill['id']}", headers=auth_headers(abc.owner))
    body = resp.json()
    assert body["status"] == "active"
    assert body["active_version_id"] == version_id

    resp = client.get("/departments/operations/active-skills", headers=auth_headers(abc.owner))
    ids = [s["id"] for s in resp.json()]
    assert skill["id"] in ids


def test_non_owner_cannot_approve(client, orgs):
    abc = orgs["abc"]
    skill = _create_skill(client, abc.owner)
    version_id = skill["versions"][0]["id"]
    client.post(f"/skills/{skill['id']}/versions/{version_id}/submit-for-review", headers=auth_headers(abc.member))

    resp = client.post(
        f"/skills/{skill['id']}/versions/{version_id}/approve",
        headers=auth_headers(abc.member),
    )
    assert resp.status_code == 403


def test_disabled_skill_excluded_from_runtime_selection(client, orgs):
    abc = orgs["abc"]
    skill = _create_skill(client, abc.owner)
    version_id = skill["versions"][0]["id"]
    _submit_and_approve(client, abc.owner, skill["id"], version_id)

    client.post(
        f"/skills/{skill['id']}/versions/{version_id}/activate",
        headers=auth_headers(abc.owner),
    )
    resp = client.get("/departments/operations/active-skills", headers=auth_headers(abc.owner))
    assert skill["id"] in [s["id"] for s in resp.json()]

    resp = client.post(f"/skills/{skill['id']}/disable", headers=auth_headers(abc.owner))
    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"

    resp = client.get("/departments/operations/active-skills", headers=auth_headers(abc.owner))
    assert skill["id"] not in [s["id"] for s in resp.json()]


def test_non_owner_cannot_disable_skill(client, orgs):
    """Disable is owner-only, same as activation - a member cannot disable a skill."""
    abc = orgs["abc"]
    skill = _create_skill(client, abc.owner)

    resp = client.post(f"/skills/{skill['id']}/disable", headers=auth_headers(abc.member))
    assert resp.status_code == 403

    resp = client.get(f"/skills/{skill['id']}", headers=auth_headers(abc.owner))
    assert resp.json()["status"] != "disabled"


def test_active_version_is_immutable_at_application_level(client, orgs):
    """
    There is no update/edit endpoint for a version - the only way to change
    behavior is to create a brand new version. This test asserts that the
    activated version's content is unchanged after further lifecycle
    events, and that no route exists to mutate one directly.

    NOTE: this only proves immutability is upheld by the application's
    routes. It does NOT prove the database itself would reject a raw SQL
    UPDATE - that is covered separately by
    tests/test_db_level_immutability.py, which requires a real Postgres
    connection (TEST_DATABASE_URL) since SQLite doesn't get the enforcement
    triggers defined in the Postgres-only migration.
    """
    abc = orgs["abc"]
    skill = _create_skill(client, abc.owner)
    v1_id = skill["versions"][0]["id"]
    _submit_and_approve(client, abc.owner, skill["id"], v1_id)
    client.post(f"/skills/{skill['id']}/versions/{v1_id}/activate", headers=auth_headers(abc.owner))

    resp = client.get(f"/skills/{skill['id']}", headers=auth_headers(abc.owner))
    v1_before = next(v for v in resp.json()["versions"] if v["id"] == v1_id)

    resp = client.post(
        f"/skills/{skill['id']}/versions",
        json={"instructions": "Updated estimate logic v2.", "requested_tools": ["generate_report"]},
        headers=auth_headers(abc.owner),
    )
    assert resp.status_code == 201
    v2 = resp.json()
    assert v2["version_number"] == 2
    _submit_and_approve(client, abc.owner, skill["id"], v2["id"])
    client.post(f"/skills/{skill['id']}/versions/{v2['id']}/activate", headers=auth_headers(abc.owner))

    resp = client.get(f"/skills/{skill['id']}", headers=auth_headers(abc.owner))
    body = resp.json()
    v1_after = next(v for v in body["versions"] if v["id"] == v1_id)

    assert v1_after["instructions"] == v1_before["instructions"]
    assert v1_after["status"] == "superseded"
    assert body["active_version_id"] == v2["id"]

    resp = client.put(f"/skills/{skill['id']}/versions/{v1_id}", json={"instructions": "hacked"})
    assert resp.status_code in (404, 405)


def test_duplicate_activation_is_idempotent(client, orgs):
    abc = orgs["abc"]
    skill = _create_skill(client, abc.owner)
    version_id = skill["versions"][0]["id"]
    _submit_and_approve(client, abc.owner, skill["id"], version_id)

    resp1 = client.post(
        f"/skills/{skill['id']}/versions/{version_id}/activate",
        headers=auth_headers(abc.owner),
    )
    resp2 = client.post(
        f"/skills/{skill['id']}/versions/{version_id}/activate",
        headers=auth_headers(abc.owner),
    )
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["id"] == resp2.json()["id"]
    assert resp2.json()["status"] == "active"

    resp = client.get(f"/skills/{skill['id']}", headers=auth_headers(abc.owner))
    active_versions = [v for v in resp.json()["versions"] if v["status"] == "active"]
    assert len(active_versions) == 1


def test_draft_skill_not_returned_as_active(client, orgs):
    abc = orgs["abc"]
    _create_skill(client, abc.owner)  # never submitted, approved, or activated

    resp = client.get("/departments/operations/active-skills", headers=auth_headers(abc.owner))
    assert resp.json() == []
