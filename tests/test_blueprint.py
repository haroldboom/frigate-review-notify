"""Behaviour of the lean Frigate review notification blueprint."""

import pytest
from homeassistant.setup import async_setup_component

from .conftest import ALARM, AWAY, STORE, TIMER

AUTOMATION = "automation.frigate_test"


def push(call):
    return call.data["data"]["push"]


async def test_new_alert_is_loud(hass, setup):
    send, calls = await setup()
    await send("new")
    assert len(calls) == 1
    d = calls[0].data
    assert d["title"] == "Frigate Notification"
    assert d["message"] == "A Person was detected on the Driveway camera."
    data = d["data"]
    assert data["tag"] == "frigate-1700000000.1-abc123"
    assert data["attachment"] == {
        "url": "https://ha.example.org/api/frigate/notifications/1700000000.0-evt001/snapshot.jpg?crop=1",
        "content-type": "jpeg"}
    assert data["url"] == data["clickAction"] == "/frigate-proxy/dashboard"
    assert push(calls[0]) == {"sound": "default", "interruption-level": "active"}
    assert [a["title"] for a in data["actions"]] == ["View Clip", "View Snapshot"]
    assert data["actions"][0]["uri"] == (
        "https://ha.example.org/api/frigate/notifications/1700000000.0-evt001/driveway/clip.mp4")


async def test_filters_block(hass, setup):
    send, calls = await setup()
    await send("new", objects=("dog",))                 # object not wanted
    await send("new", camera="doorbell")                # camera not selected
    hass.states.async_set(ALARM, "disarmed")
    await send("new")                                   # alarm not armed
    assert calls == []


async def test_detection_severity_never_starts_a_run(hass, setup):
    send, calls = await setup()
    await send("new", severity="detection")
    assert calls == []
    assert hass.states.get(AUTOMATION).attributes["last_triggered"] is None


async def test_upgrade_to_alert_is_loud(hass, setup):
    """A review that starts as a detection and becomes an alert still makes a sound."""
    send, calls = await setup()
    await send("new", severity="detection")
    await send("update", severity="alert", before={"severity": "detection"})
    assert len(calls) == 1
    assert push(calls[0])["sound"] == "default"


async def test_wanted_object_arriving_later_is_loud(hass, setup):
    send, calls = await setup()
    await send("new", objects=("dog",))
    await send("update", objects=("dog", "person"), before={"objects": ("dog",)})
    assert len(calls) == 1
    assert push(calls[0])["sound"] == "default"
    assert calls[0].data["message"] == "A Person was detected on the Driveway camera."


async def test_updates_are_silent_and_only_on_change(hass, setup):
    send, calls = await setup()
    await send("new")
    await send("update")                                                # nothing changed
    await send("update", objects=("person", "dog"), before={"objects": ("person",)})  # unwanted object
    assert len(calls) == 1
    await send("update", objects=("person", "car"), before={"objects": ("person",)})
    assert len(calls) == 2
    d = calls[1].data
    assert d["message"] == "A Person, Car was detected on the Driveway camera."
    assert push(calls[1]) == {"sound": "none", "interruption-level": "passive"}
    assert d["data"]["tag"] == calls[0].data["data"]["tag"]
    assert d["data"]["attachment"] == {
        "url": "https://ha.example.org/api/frigate/notifications/1700000000.1-abc123/review_preview.gif",
        "content-type": "gif"}


async def test_end_update_is_optional(hass, setup):
    send, calls = await setup()
    await send("new")
    await send("end")
    assert len(calls) == 1


async def test_end_update_enabled(hass, setup):
    send, calls = await setup(end_update=True)
    await send("new")
    await send("end")
    assert len(calls) == 2
    assert push(calls[1])["sound"] == "none"


async def test_genai_summary(hass, setup):
    send, calls = await setup()
    await send("new")
    await send("end")
    await send("genai", metadata={"title": "Person at the gate", "shortSummary": "A man opened the gate.",
                                  "scene": "long text", "potential_threat_level": 1})
    assert len(calls) == 2
    d = calls[1].data
    assert d["title"] == "Needs Review: Person at the gate"
    assert d["message"] == "A man opened the gate."
    assert push(calls[1])["sound"] == "none"
    assert d["data"]["tag"] == calls[0].data["data"]["tag"]


async def test_genai_falls_back_to_scene_then_to_normal_text(hass, setup):
    send, calls = await setup()
    await send("genai", metadata={"title": "Car", "scene": "A car parked.", "potential_threat_level": 0})
    assert calls[0].data["title"] == "Car"
    assert calls[0].data["message"] == "A car parked."
    await send("genai", metadata={})
    assert calls[1].data["title"] == "Frigate Notification"
    assert calls[1].data["message"] == "A Person was detected on the Driveway camera."


async def test_genai_respects_filters_and_toggle(hass, setup):
    send, calls = await setup(genai_summary=False)
    await send("genai", metadata={"title": "t", "shortSummary": "s"})
    assert calls == []


async def test_genai_without_before(hass, setup):
    """Tolerate a genai message that carries no before state."""
    import json
    from pytest_homeassistant_custom_component.common import async_fire_mqtt_message
    from .conftest import review
    send, calls = await setup()
    payload = json.loads(review("genai", metadata={"title": "t", "shortSummary": "s"}))
    del payload["before"]
    async_fire_mqtt_message(hass, "frigate/reviews", json.dumps(payload))
    await hass.async_block_till_done()
    assert len(calls) == 1 and calls[0].data["message"] == "s"


async def test_verified_object_counts_as_its_label(hass, setup):
    send, calls = await setup()
    await send("new", objects=("person-verified",), sub_labels=("Bob",))
    assert calls[0].data["message"] == "A Person was detected on the Driveway camera."
    # person -> person-verified is not a change
    await send("update", objects=("person", "person-verified"), before={"objects": ("person",)})
    assert len(calls) == 1


async def test_no_label_filter_and_custom_message(hass, setup):
    send, calls = await setup({**AWAY, "labels": [], "state_entity": "", "state_values": [],
                               "message": "{{ label }} / {{ sub_labels | join(',') }} / {{ camera }}"})
    await send("new", objects=("dog", "delivery_truck"), sub_labels=("ups",))
    assert calls[0].data["message"] == "Dog, Delivery Truck / ups / driveway"


async def test_many_concurrent_reviews(hass, setup):
    """Every review alerts, however many are open at once."""
    send, calls = await setup()
    for i in range(25):
        await send("new", rid=f"1700000000.{i}-abc123")
    assert len(calls) == 25
    assert hass.states.get(AUTOMATION).attributes["current"] == 0


async def test_silence_button(hass, setup):
    send, calls = await setup(silence_timer=TIMER, silence_minutes=45)
    await send("new")
    actions = calls[0].data["data"]["actions"]
    assert actions[-1] == {"action": f"silence-{TIMER}", "title": "Silence 45 min", "destructive": True}

    hass.bus.async_fire("mobile_app_notification_action", {"action": f"silence-{TIMER}"})
    await hass.async_block_till_done()
    timer = hass.states.get(TIMER)
    assert timer.state == "active" and timer.attributes["duration"] == "0:45:00"
    await send("new", rid="1700000001.1-def456")
    assert len(calls) == 1

    await hass.services.async_call("timer", "cancel", {"entity_id": TIMER}, blocking=True)
    await send("new", rid="1700000002.1-ghi789")
    assert len(calls) == 2


async def test_other_notification_actions_are_ignored(hass, setup):
    send, calls = await setup(silence_timer=TIMER)
    hass.bus.async_fire("mobile_app_notification_action", {"action": "silence-timer.other"})
    await hass.async_block_till_done()
    assert hass.states.get(TIMER).state == "idle"


async def test_doorbell_config(hass, setup):
    """Same image throughout, HLS clip link, state filter on a door sensor."""
    hass.states.async_set("binary_sensor.front_door", "off")
    gif = "{{base_url}}/api/frigate{{client_id}}/notifications/{{review_id}}/review_preview.gif"
    send, calls = await setup({
        "cameras": ["camera.doorbell"], "notify_action": "all_phones",
        "base_url": "https://ha.example.org", "labels": ["person"],
        "state_entity": "binary_sensor.front_door", "state_values": ["unknown", "unavailable", "off"],
        "image": gif, "update_image": "",
        "clip_url": "{{base_url}}/api/frigate{{client_id}}/notifications/{{id}}/{{camera}}/master.m3u8"})
    await send("new", camera="doorbell")
    data = calls[0].data["data"]
    assert data["attachment"]["url"].endswith("/1700000000.1-abc123/review_preview.gif")
    assert data["attachment"]["content-type"] == "gif"
    assert data["actions"][0]["uri"].endswith("/1700000000.0-evt001/doorbell/master.m3u8")
    assert calls[0].data["title"] == "Doorbell"
    hass.states.async_set("binary_sensor.front_door", "on")
    await send("new", camera="doorbell", rid="1700000005.1-zzz999")
    assert len(calls) == 1


def sounds(calls):
    return [push(c)["sound"] for c in calls]


async def test_cooldown_is_per_camera(hass, setup, freezer):
    send, calls = await setup(cooldown=60, cooldown_store=STORE)
    await send("new", rid="1.1-a")
    freezer.tick(20)
    await send("new", rid="2.1-b")                          # same camera, inside the window
    await send("new", rid="3.1-c", camera="front_yard")     # another camera
    assert sounds(calls) == ["default", "none", "default"]
    quiet = calls[1].data["data"]
    assert quiet["tag"] == "frigate-2.1-b"
    assert quiet["push"]["interruption-level"] == "passive"
    assert (quiet["channel"], quiet["importance"]) == ("Frigate quiet", "low")
    assert quiet["attachment"]["url"].endswith("/snapshot.jpg?crop=1")   # no preview GIF yet
    assert (calls[0].data["data"]["channel"], calls[0].data["data"]["importance"]) == ("", "")

    freezer.tick(45)                                        # 65 s after the first alert
    await send("new", rid="4.1-d")
    assert sounds(calls)[-1] == "default"


async def test_cooldown_counts_from_the_last_alert_with_sound(hass, setup, freezer):
    """Silent deliveries and updates do not extend the window."""
    send, calls = await setup(cooldown=60, cooldown_store=STORE, end_update=True)
    await send("new", rid="1.1-a")
    freezer.tick(50)
    await send("new", rid="2.1-b")
    await send("update", rid="2.1-b", objects=("person", "car"), before={"objects": ("person",)})
    await send("end", rid="2.1-b", objects=("person", "car"))
    freezer.tick(15)
    await send("new", rid="3.1-c")
    assert sounds(calls) == ["default", "none", "none", "none", "default"]


async def test_cooldown_ignores_filtered_reviews(hass, setup, freezer):
    send, calls = await setup(cooldown=60, cooldown_store=STORE)
    await send("new", rid="1.1-a", objects=("dog",))
    hass.states.async_set(ALARM, "disarmed")
    await send("new", rid="2.1-b")
    hass.states.async_set(ALARM, "armed_away")
    await send("new", rid="3.1-c")
    assert sounds(calls) == ["default"]


async def test_cooldown_store_holds_only_live_entries(hass, setup, freezer):
    send, calls = await setup(cooldown=60, cooldown_store=STORE)
    assert hass.states.get(STORE).state == "unknown"
    await send("new", rid="1.1-a")
    first = hass.states.get(STORE).state
    assert first.startswith("driveway:")
    freezer.tick(30)
    await send("new", rid="2.1-b", camera="front_yard")
    assert hass.states.get(STORE).state.split(",")[1] == first
    freezer.tick(40)
    await send("new", rid="3.1-c")
    cams = [item.split(":")[0] for item in hass.states.get(STORE).state.split(",")]
    assert cams == ["driveway", "front_yard"]


async def test_cooldown_helper_too_short_drops_the_oldest(hass, setup, freezer):
    short = "input_text.short_cooldown"                     # max 30: room for one camera
    send, calls = await setup(cooldown=60, cooldown_store=short)
    await send("new", rid="1.1-a")
    await send("new", rid="2.1-b", camera="front_yard")
    assert hass.states.get(short).state.startswith("front_yard:")
    await send("new", rid="3.1-c", camera="front_yard")
    await send("new", rid="4.1-d")                          # forgotten, so it sounds again
    assert sounds(calls) == ["default", "default", "none", "default"]


async def test_cooldown_without_a_helper_does_nothing(hass, setup):
    send, calls = await setup(cooldown=60)
    await send("new", rid="1.1-a")
    await send("new", rid="2.1-b")
    assert sounds(calls) == ["default", "default"]


@pytest.mark.allow_warning("input_text.missing are missing")
async def test_cooldown_with_a_missing_helper_does_nothing(hass, setup):
    send, calls = await setup(cooldown=60, cooldown_store="input_text.missing")
    await send("new", rid="1.1-a")
    await send("new", rid="2.1-b")
    assert sounds(calls) == ["default", "default"]
    assert hass.states.get(AUTOMATION).attributes["current"] == 0


async def test_cooldown_survives_a_garbled_helper(hass, setup):
    send, calls = await setup(cooldown=60, cooldown_store=STORE)
    await hass.services.async_call("input_text", "set_value", {"entity_id": STORE, "value": "hello, :, driveway:x"}, blocking=True)
    await send("new", rid="1.1-a")
    await send("new", rid="2.1-b")
    assert sounds(calls) == ["default", "none"]
    assert hass.states.get(STORE).state.count(",") == 0


async def test_extra_conditions(hass, setup):
    hass.states.async_set("input_boolean.guard", "off")
    send, calls = await setup(extra_conditions=[
        {"condition": "state", "entity_id": "input_boolean.guard", "state": "on"}])
    await send("new")
    assert calls == []
    hass.states.async_set("input_boolean.guard", "on")
    await send("new", rid="1700000009.1-qqq111")
    assert len(calls) == 1


async def test_default_severities_include_detections(hass, setup):
    inputs = {k: v for k, v in AWAY.items() if k != "severities"}
    send, calls = await setup(inputs)
    await send("new", severity="detection")
    await send("update", severity="alert", before={"severity": "detection"})   # already alerted
    assert len(calls) == 1
    assert push(calls[0])["sound"] == "default"


async def test_example_automations_load(hass, setup):
    """The ready-made automations in examples/ are valid against the blueprint."""
    from pathlib import Path
    import yaml
    configs = []
    for name in ("away", "doorbell"):
        cfg = yaml.safe_load((Path(__file__).parent.parent / "examples" / f"{name}.yaml").read_text())
        cfg["use_blueprint"]["path"] = "test/frigate_review_notify.yaml"
        configs.append(cfg)
    assert await async_setup_component(hass, "automation", {"automation": configs})
    await hass.async_block_till_done()
    for entity in ("automation.camera_notifications_away", "automation.camera_notifications_doorbell"):
        assert hass.states.get(entity).state == "on"
