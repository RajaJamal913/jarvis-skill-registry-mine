from tests.conftest import auth_headers


def test_audit_log_records_creation_and_activation(client, orgs):
    abc = orgs["abc"]
    resp = client.post(
        "/skills",
        json={
            "name": "Payroll Summary Bot",
            "department": "operations",
            "instructions": "Summarize weekly payroll totals.",
            "requested_tools": ["generate_report"],
        },
        headers=auth_headers(abc.owner),
    )
    skill = resp.json()
    version_id = skill["versions"][0]["id"]

    client.post(
        f"/skills/{skill['id']}/versions/{version_id}/submit-for-review",
        headers=auth_headers(abc.owner),
    )
    client.post(
        f"/skills/{skill['id']}/versions/{version_id}/approve",
        headers=auth_headers(abc.owner),
    )
    client.post(
        f"/skills/{skill['id']}/versions/{version_id}/activate",
        headers=auth_headers(abc.owner),
    )

    resp = client.get("/audit-logs", headers=auth_headers(abc.owner))
    assert resp.status_code == 200
    events = resp.json()

    creation = next(e for e in events if e["event_type"] == "skill_draft_created")
    activation = next(e for e in events if e["event_type"] == "skill_activated")

    for entry in (creation, activation):
        assert entry["organization_id"] == abc.org.id
        assert entry["actor_user_id"] == abc.owner.id
        assert entry["skill_id"] == skill["id"]
        assert entry["version_id"] == version_id


def test_audit_log_is_org_scoped(client, orgs):
    abc, xyz = orgs["abc"], orgs["xyz"]

    client.post(
        "/skills",
        json={
            "name": "ABC-only skill",
            "department": "operations",
            "instructions": "Something ABC-specific.",
            "requested_tools": [],
        },
        headers=auth_headers(abc.owner),
    )

    resp = client.get("/audit-logs", headers=auth_headers(xyz.owner))
    assert resp.status_code == 200
    assert resp.json() == []  # XYZ sees none of ABC's audit trail
