from tests.conftest import auth_headers


def test_invalid_unrecognized_tool_is_rejected(client, orgs):
    abc = orgs["abc"]
    resp = client.post(
        "/skills",
        json={
            "name": "Mystery Skill",
            "department": "operations",
            "instructions": "Does something.",
            "requested_tools": ["totally_made_up_tool"],
        },
        headers=auth_headers(abc.owner),
    )
    assert resp.status_code == 400
    assert "not a recognized" in resp.json()["detail"].lower()


def test_destructive_tool_is_rejected(client, orgs):
    abc = orgs["abc"]
    for bad_tool in ["delete_all_records", "drop_database", "shell_exec", "wipe_customer_data"]:
        resp = client.post(
            "/skills",
            json={
                "name": "Dangerous Skill",
                "department": "operations",
                "instructions": "Does something risky.",
                "requested_tools": [bad_tool],
            },
            headers=auth_headers(abc.owner),
        )
        assert resp.status_code == 400, f"{bad_tool} should have been rejected"


def test_requesting_a_tool_does_not_grant_it(client, orgs):
    abc = orgs["abc"]
    resp = client.post(
        "/skills",
        json={
            "name": "Emailer",
            "department": "operations",
            "instructions": "Sends status update emails.",
            "requested_tools": ["send_email"],
        },
        headers=auth_headers(abc.owner),
    )
    assert resp.status_code == 201
    version = resp.json()["versions"][0]
    assert version["requested_tools"] == ["send_email"]
    assert version["granted_tools"] == []  # never auto-granted


def test_valid_tools_are_accepted(client, orgs):
    abc = orgs["abc"]
    resp = client.post(
        "/skills",
        json={
            "name": "Scheduler",
            "department": "operations",
            "instructions": "Schedules follow-up meetings.",
            "requested_tools": ["schedule_meeting", "read_calendar"],
        },
        headers=auth_headers(abc.owner),
    )
    assert resp.status_code == 201


def test_blank_instructions_rejected(client, orgs):
    abc = orgs["abc"]
    resp = client.post(
        "/skills",
        json={
            "name": "Blank",
            "department": "operations",
            "instructions": "   ",
            "requested_tools": [],
        },
        headers=auth_headers(abc.owner),
    )
    assert resp.status_code == 422
