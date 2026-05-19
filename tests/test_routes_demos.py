"""Public lifecycle endpoints."""


def test_start_when_terminated_starts_vm(client, mock_compute):
    mock_compute.set_state("cs5", "TERMINATED")
    r = client.post("/demos/cs5/start")
    assert r.status_code == 200
    body = r.json()
    assert body["already_running"] is False
    assert body["session_id"]
    assert len(mock_compute.starts) == 1


def test_start_when_already_running_does_not_call_start(client, mock_compute):
    mock_compute.set_state("cs5", "RUNNING")
    r = client.post("/demos/cs5/start")
    assert r.status_code == 200
    assert r.json()["already_running"] is True
    assert len(mock_compute.starts) == 0


def test_start_already_running_marks_manual_if_unowned(client, mock_compute):
    mock_compute.set_state("cs5", "RUNNING")
    client.post("/demos/cs5/start")
    from app.state import get
    assert get("cs5").started_by == "manual"


def test_start_unknown_demo_404(client, mock_compute):
    r = client.post("/demos/does-not-exist/start")
    assert r.status_code == 404


def test_status_terminated(client, mock_compute):
    mock_compute.set_state("cs5", "TERMINATED")
    r = client.get("/demos/cs5/status")
    assert r.status_code == 200
    assert r.json()["state"] == "stopped"


def test_status_running_and_healthy(client, mock_compute):
    mock_compute.set_state("cs5", "RUNNING")
    r = client.get("/demos/cs5/status")
    assert r.status_code == 200
    assert r.json()["state"] == "ready"


def test_status_running_but_unhealthy(client, mock_compute, mocker):
    mock_compute.set_state("cs5", "RUNNING")
    mocker.patch("app.routes.demos._check_app_healthy", return_value=False)
    r = client.get("/demos/cs5/status")
    assert r.status_code == 200
    assert r.json()["state"] == "booting"


def test_status_unknown_demo_404(client, mock_compute):
    r = client.get("/demos/nope/status")
    assert r.status_code == 404


def test_heartbeat_matching_session_accepted(client, mock_compute):
    mock_compute.set_state("cs5", "TERMINATED")
    sid = client.post("/demos/cs5/start").json()["session_id"]
    r = client.post("/demos/cs5/heartbeat", json={"session_id": sid})
    assert r.status_code == 200
    assert r.json()["accepted"] is True


def test_heartbeat_mismatch_rejected(client, mock_compute):
    mock_compute.set_state("cs5", "TERMINATED")
    client.post("/demos/cs5/start")
    r = client.post("/demos/cs5/heartbeat", json={"session_id": "wrong"})
    assert r.status_code == 200
    assert r.json()["accepted"] is False


def test_release_portfolio_owned_stops_vm(client, mock_compute):
    mock_compute.set_state("cs5", "TERMINATED")
    sid = client.post("/demos/cs5/start").json()["session_id"]
    mock_compute.set_state("cs5", "RUNNING")  # simulate boot completed
    r = client.post("/demos/cs5/release", json={"session_id": sid})
    assert r.status_code == 200
    assert r.json()["released"] is True
    assert len(mock_compute.stops) == 1


def test_release_manual_owned_does_not_stop(client, mock_compute):
    mock_compute.set_state("cs5", "RUNNING")
    sid = client.post("/demos/cs5/start").json()["session_id"]  # marks manual
    r = client.post("/demos/cs5/release", json={"session_id": sid})
    assert r.status_code == 200
    assert r.json()["released"] is False
    assert len(mock_compute.stops) == 0


def test_release_wrong_session_does_not_stop(client, mock_compute):
    mock_compute.set_state("cs5", "TERMINATED")
    client.post("/demos/cs5/start")
    r = client.post("/demos/cs5/release", json={"session_id": "wrong"})
    assert r.status_code == 200
    assert r.json()["released"] is False
    assert len(mock_compute.stops) == 0

def test_status_stopping(client, mock_compute):
    mock_compute.set_state("cs5", "STOPPING")
    r = client.get("/demos/cs5/status")
    assert r.status_code == 200
    assert r.json()["state"] == "stopping"


def test_status_provisioning_is_starting(client, mock_compute):
    """Non-STOPPING transient states still map to 'starting'."""
    mock_compute.set_state("cs5", "PROVISIONING")
    r = client.get("/demos/cs5/status")
    assert r.status_code == 200
    assert r.json()["state"] == "starting"