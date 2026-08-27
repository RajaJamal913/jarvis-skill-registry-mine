from tests.conftest import auth_headers


def _create_skill(client, user, name="Invoice Drafting Assistant"):
    resp = client.post(
        "/skills",
        json={
            "name": name,
            "department": "operations",
            "instructions": "Draft invoices from approved purchase orders.",
            "requested_tools": ["create_invoice_draft"],
        },
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_same_org_create_and_read_succeeds(client, orgs):
    owner = orgs["abc"].owner
    skill = _create_skill(client, owner)

    resp = client.get(f"/skills/{skill['id']}", headers=auth_headers(owner))
    assert resp.status_code == 200
    assert resp.json()["id"] == skill["id"]
    assert resp.json()["organization_id"] == orgs["abc"].org.id


def test_cross_org_read_is_denied(client, orgs):
    abc_owner = orgs["abc"].owner
    xyz_owner = orgs["xyz"].owner

    skill = _create_skill(client, abc_owner)

    resp = client.get(f"/skills/{skill['id']}", headers=auth_headers(xyz_owner))
    assert resp.status_code == 404  # existence is not leaked either


def test_cross_org_update_is_denied(client, orgs):
    abc_owner = orgs["abc"].owner
    xyz_owner = orgs["xyz"].owner

    skill = _create_skill(client, abc_owner)

    resp = client.post(
        f"/skills/{skill['id']}/versions",
        json={"instructions": "Malicious edit attempt.", "requested_tools": []},
        headers=auth_headers(xyz_owner),
    )
    assert resp.status_code == 404


def test_cross_org_activation_is_denied(client, orgs):
    abc_owner = orgs["abc"].owner
    xyz_owner = orgs["xyz"].owner

    skill = _create_skill(client, abc_owner)
    version_id = skill["versions"][0]["id"]
    client.post(f"/skills/{skill['id']}/versions/{version_id}/submit-for-review", headers=auth_headers(abc_owner))
    client.post(f"/skills/{skill['id']}/versions/{version_id}/approve", headers=auth_headers(abc_owner))

    resp = client.post(
        f"/skills/{skill['id']}/versions/{version_id}/activate",
        headers=auth_headers(xyz_owner),
    )
    assert resp.status_code == 404


def test_list_skills_only_returns_own_org(client, orgs):
    abc_owner = orgs["abc"].owner
    xyz_owner = orgs["xyz"].owner

    _create_skill(client, abc_owner, name="ABC Skill 1")
    _create_skill(client, xyz_owner, name="XYZ Skill 1")

    resp = client.get("/skills", headers=auth_headers(abc_owner))
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()]
    assert names == ["ABC Skill 1"]


def test_non_owner_activation_is_denied(client, orgs):
    abc = orgs["abc"]
    skill = _create_skill(client, abc.owner)
    version_id = skill["versions"][0]["id"]
    client.post(f"/skills/{skill['id']}/versions/{version_id}/submit-for-review", headers=auth_headers(abc.owner))
    client.post(f"/skills/{skill['id']}/versions/{version_id}/approve", headers=auth_headers(abc.owner))

    resp = client.post(
        f"/skills/{skill['id']}/versions/{version_id}/activate",
        headers=auth_headers(abc.member),
    )
    assert resp.status_code == 403


def test_missing_api_key_is_rejected(client, orgs):
    resp = client.get("/skills")
    assert resp.status_code == 401


def test_invalid_api_key_is_rejected(client, orgs):
    resp = client.get("/skills", headers={"X-API-Key": "not-a-real-key"})
    assert resp.status_code == 401
