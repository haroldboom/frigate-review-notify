"""Fixtures: a Home Assistant instance with the blueprint installed."""

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    async_fire_mqtt_message,
    async_mock_service,
)

pytest_plugins = "pytest_homeassistant_custom_component"

BLUEPRINT = Path(__file__).parent.parent / "frigate_review_notify.yaml"
ALARM = "alarm_control_panel.house"
TIMER = "timer.frigate_silence"

AWAY = {
    "cameras": ["camera.driveway", "camera.front_yard"],
    "notify_action": "notify.all_phones",
    "base_url": "https://ha.example.org/",
    "severities": ["alert"],
    "labels": ["person", "car"],
    "state_entity": ALARM,
    "state_values": ["armed_away", "armed_home"],
    "title": "Frigate Notification",
    "tap_action": "/frigate-proxy/dashboard",
}


def review(type_, severity="alert", objects=("person",), camera="driveway",
           rid="1700000000.1-abc123", before=None, metadata=None, sub_labels=()):
    """Build a frigate/reviews payload. `before` overrides fields of the before state."""
    def state(sev, objs, meta=None):
        data = {"detections": ["1700000000.0-evt001"], "objects": list(objs),
                "sub_labels": list(sub_labels), "zones": [], "audio": []}
        if meta is not None:
            data["metadata"] = meta
        return {"id": rid, "camera": camera, "start_time": 1700000000.1,
                "end_time": None, "severity": sev, "data": data}

    b = {"severity": severity, "objects": objects, **(before or {})}
    return json.dumps({"type": type_,
                       "before": state(b["severity"], b["objects"]),
                       "after": state(severity, objects, metadata)})


@pytest.fixture
async def setup(hass, mqtt_mock):
    """Return a coroutine that installs the automation and a send() helper."""
    dest = Path(hass.config.path("blueprints/automation/test"))
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINT, dest / BLUEPRINT.name)

    assert await async_setup_component(hass, "timer", {"timer": {"frigate_silence": {}}})
    hass.states.async_set(ALARM, "armed_away")
    for cam in ("driveway", "front_yard", "doorbell"):
        hass.states.async_set(f"camera.{cam}", "idle", {"camera_name": cam})
    calls = async_mock_service(hass, "notify", "all_phones")

    async def _setup(inputs=None, **extra):
        cfg = {"alias": "frigate test", "use_blueprint": {
            "path": f"test/{BLUEPRINT.name}", "input": {**(inputs or AWAY), **extra}}}
        assert await async_setup_component(hass, "automation", {"automation": cfg})
        await hass.async_block_till_done()
        assert hass.states.get("automation.frigate_test") is not None

        async def send(*args, settle=None, **kwargs):
            """Publish a review message. A run holding a cooldown never settles, so
            tests with a cooldown pass the time to wait instead."""
            async_fire_mqtt_message(hass, "frigate/reviews", review(*args, **kwargs))
            if settle is None:
                await hass.async_block_till_done()
            else:
                await asyncio.sleep(settle)

        return send, calls

    yield _setup
    shutil.rmtree(dest, ignore_errors=True)


@pytest.fixture
def expected_lingering_timers():
    """The mocked MQTT client leaves its housekeeping timer behind."""
    return True


@pytest.fixture(autouse=True)
def no_ha_warnings(request, caplog):
    """Fail on template errors and other Home Assistant warnings a test did not expect."""
    yield
    allowed = [m.args[0] for m in request.node.iter_markers("allow_warning")]
    bad = [r.getMessage() for r in caplog.get_records("call")
           if r.levelno >= 30 and r.name.startswith("homeassistant")
           and not any(text in r.getMessage() for text in allowed)]
    assert not bad, bad
