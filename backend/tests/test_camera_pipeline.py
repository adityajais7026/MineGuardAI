"""Phase 10 camera event pipeline + detector honesty tests."""


def test_detector_factory_defaults_to_simulated():
    from app.ai.detector import SimulatedDetector, get_detector

    detector = get_detector()
    assert isinstance(detector, SimulatedDetector)
    assert detector.source == "simulated"


def test_simulated_detection_labels_itself_honestly():
    from app.ai.detector import SimulatedDetector

    d = SimulatedDetector().detect("CAM-TEST")
    assert d.detection_source == "simulated"
    assert 0 <= d.confidence <= 1
    assert d.event_type in {
        "person_without_helmet", "person_without_vest", "restricted_zone_entry",
        "vehicle_in_restricted_area", "fire_smoke", "unsafe_crowding",
    }


def test_yolo_detector_not_silently_available():
    """With AI_DETECTOR=simulated (default), no YOLO model is loaded/executed."""
    from app.core.config import settings
    from app.ai.detector import get_detector

    if settings.AI_DETECTOR == "yolo":
        # Only in an environment that explicitly opted in with weights present.
        detector = get_detector()
        assert detector.source in {"yolo", "simulated"}
    else:
        detector = get_detector()
        assert detector.source == "simulated"  # never pretends to be YOLO


def test_simulate_event_endpoint_creates_event(client):
    r = client.post("/api/ai/simulate-event", params={"mine_id": "m-test-0001", "camera_id": "CAM-T1"})
    assert r.status_code == 201
    body = r.json()
    assert body["event"]["detection_source"] == "simulated"
    assert "not real computer vision" in body["note"]


def test_simulate_event_with_zone_raises_alert(client):
    # restricted-zone events have 'critical' severity -> alert required
    got_alert = False
    for _ in range(10):  # simulated types vary; retry until a zone event fires
        r = client.post("/api/ai/simulate-event", params={
            "mine_id": "m-test-0001", "zone_id": "z-test-0001",
        })
        assert r.status_code == 201
        body = r.json()
        if body["alert"] is not None:
            got_alert = True
            alert = client.get(f"/api/alerts/{body['alert']['id']}").json()
            assert alert["source"] == "camera_pipeline"
            assert alert["source_event_id"] == body["event"]["id"]
            assert "simulated" in alert["description"].lower()
            break
    assert got_alert, "no alert raised after 10 simulated zone events"


def test_simulate_event_unknown_mine_400(client):
    r = client.post("/api/ai/simulate-event", params={"mine_id": "ghost"})
    assert r.status_code == 400


def test_simulate_event_cross_mine_zone_400(client):
    r = client.post("/api/ai/simulate-event", params={
        "mine_id": "m-test-0001", "zone_id": "z-test-0002",
    })
    assert r.status_code == 400


def test_detector_info_endpoint(client):
    r = client.get("/api/ai/detector")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] in {"simulated", "yolo"}
    assert body["available"] is True
