# Frigate Review Notifications (lean)

A small Home Assistant automation blueprint that sends [Frigate](https://frigate.video) review
items to the Home Assistant Companion app.

[![Import the blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fharoldboom%2Ffrigate-review-notify%2Fblob%2Fmain%2Ffrigate_review_notify.yaml)

## What it does

- **One alert with sound per review**, the first time the review matches your filters. That
  includes a review that starts as a detection and becomes an alert, and a review where the
  object you care about turns up after something else started it.
- **Silent updates of that same notification** when another wanted object joins, when
  Frigate publishes a GenAI summary, and optionally when the review ends.
- **Per-camera cooldown** (optional): after an alert with sound, new reviews on that camera
  arrive silently for a while. Other cameras still alert. No helper needed.
- **Silence button** (optional): mutes everything for a set time using a timer helper, so it
  survives a restart.
- Filters for camera, review severity, object, the state of one entity (an alarm panel, a
  door sensor), and any extra conditions.

Every MQTT message is handled on its own, so the number of open reviews does not matter and
a Home Assistant restart mid-review loses nothing.

It has no TV, Telegram, zone, time-of-day or presence options. If you need those, use
[SgtBatten's Frigate Notifications blueprint](https://github.com/SgtBatten/HA_blueprints),
which this one borrows its ideas and URL conventions from.

## Requirements

- Home Assistant 2024.10 or newer with MQTT
- Frigate 0.14 or newer, publishing to `frigate/reviews`
- The Frigate integration with the unauthenticated notification proxy enabled
- The Companion app. Developed for iOS; the Android fields are set but have not been tried
  on a device.

## Setup

1. Import the blueprint with the button above, or paste this URL under
   **Settings → Automations & scenes → Blueprints → Import blueprint**:
   `https://github.com/haroldboom/frigate-review-notify/blob/main/frigate_review_notify.yaml`
2. Create an automation from it. Cameras, the notify action (for example
   `notify.mobile_app_my_phone` or a notify group) and your external URL are the only
   required fields.
3. For the cooldown, set the number of seconds under *Cooldown*.
4. For the silence button, create a **Timer** helper with *Restore* enabled and pick it
   under *Silence button*.

[`examples/`](examples) has two automations in the format the automation editor's YAML
mode accepts.

## Cooldown

The cooldown is kept inside the automation. The run that sent an alert with sound stays
alive until the cooldown for its camera ends, and a run about to alert asks whether one is
active for its camera.

- Reviews that start during the cooldown are still delivered, without sound (iOS: passive
  interruption level; Android: a low-importance "Frigate quiet" channel).
- Silent deliveries and updates do not extend the cooldown.
- With a cooldown set, an alert with sound goes out 0.2 s later, the time allowed for an
  answer.
- While a camera is cooling down the automation shows one running instance for it.
- Restarting Home Assistant or reloading the automation forgets running cooldowns, so the
  next review sounds.
- Each automation keeps its own cooldowns.

## Templates

Title, message, images and links accept templates. Available variables: `camera`,
`camera_name`, `label`, `sub_labels`, `id` (the first detection of the review), `review_id`,
`base_url`, `client_id`, and for the GenAI title `genai_title` and `genai_threat_level`.

## Tests

The tests load the blueprint into a real Home Assistant core and feed it Frigate review
messages.

```sh
pip install -r requirements_test.txt   # needs Python 3.14
pytest
```
