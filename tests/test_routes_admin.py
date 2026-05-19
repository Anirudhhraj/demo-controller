"""Admin endpoints + auth."""


def test_missing_token_rejected(client, mock_compute):
    r = client.get("/admin/status")
    assert r.status_code == 401


def test_wrong_token_rejected(client, mock_compute):
    r = client.get("/admin/status", headers={"X-Admin-Token": "nope"})
    assert r.status_code == 401


def test_correct_token_accepted(client, admin_token, mock_compute):
    r = client.get("/admin/status", headers={"X-Admin-Token": admin_token})
    assert r.status_code == 200


def test_status_dump_shape(client, admin_token, mock_compute):
    mock_compute.set_state("cs5", "RUNNING")
    r = client.get("/admin/status", headers={"X-Admin-Token": admin_token})
    body = r.json()
    assert set(body.keys()) == {"cs5", "vicinity"}
    assert body["cs5"]["vm_state"] == "RUNNING"
    assert body["vicinity"]["vm_state"] == "TERMINATED"


def test_lock_sets_locked_until(client, admin_token, mock_compute):
    r = client.post(
        "/admin/demos/cs5/lock?hours=2",
        headers={"X-Admin-Token": admin_token},
    )
    assert r.status_code == 200
    from app.state import get
    assert get("cs5").locked_until is not None


def test_lock_rejects_invalid_hours(client, admin_token):
    r = client.post(
        "/admin/demos/cs5/lock?hours=100",
        headers={"X-Admin-Token": admin_token},
    )
    assert r.status_code == 422


def test_unlock_clears(client, admin_token, mock_compute):
    client.post("/admin/demos/cs5/lock?hours=2", headers={"X-Admin-Token": admin_token})
    r = client.post("/admin/demos/cs5/unlock", headers={"X-Admin-Token": admin_token})
    assert r.status_code == 200
    from app.state import get
    assert get("cs5").locked_until is None


def test_take_marks_manual(client, admin_token, mock_compute):
    r = client.post("/admin/demos/cs5/take", headers={"X-Admin-Token": admin_token})
    assert r.status_code == 200
    from app.state import get
    s = get("cs5")
    assert s.started_by == "manual"
    assert s.session_id is None


def test_release_ownership_resets(client, admin_token, mock_compute):
    client.post("/admin/demos/cs5/take", headers={"X-Admin-Token": admin_token})
    r = client.post(
        "/admin/demos/cs5/release-ownership",
        headers={"X-Admin-Token": admin_token},
    )
    assert r.status_code == 200
    from app.state import get
    assert get("cs5").started_by is None


def test_admin_endpoints_404_on_unknown_demo(client, admin_token):
    r = client.post(
        "/admin/demos/does-not-exist/lock?hours=1",
        headers={"X-Admin-Token": admin_token},
    )
    assert r.status_code == 404


def test_reaper_endpoint_returns_summary(client, admin_token, mock_compute):
    r = client.post("/admin/reaper/run", headers={"X-Admin-Token": admin_token})
    assert r.status_code == 200
    body = r.json()
    assert "checked" in body and "stopped" in body and "skipped" in body
    assert body["checked"] == 2