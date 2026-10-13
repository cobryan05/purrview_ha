<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/purrview/brand/dark_logo.png">
  <img src="custom_components/purrview/brand/logo.png" alt="PurrView" width="454">
</picture>

# PurrView for Home Assistant

A HACS custom integration that brings [PurrView](https://github.com/cobryan05/purrview)
live camera views, recorded events, and detection stats into Home Assistant.

The Lovelace cards ship from inside this integration rather than as a separate HACS
frontend plugin — they are registered automatically on setup, so there is nothing to
add to your resources list.

Brand icons ship in `custom_components/purrview/brand/`, which Home Assistant 2026.3
and newer prefer over the brands CDN — nothing is registered in `home-assistant/brands`.

## What you get

- **Config flow** — add a PurrView instance by host, port, and API token.
- **Live view card** (`purrview-card`) — polls a watch profile's current frame and
  draws a toggleable overlay of detections, tracks, zones, and labels.
- **Events card** (`purrview-events-card`) — two views of the same recorded events.
  A **grid** of thumbnails with filters (camera, subject label tree, event type, date
  range), click-to-play clips and timelapses, flag for review, and pin against
  cleanup. A **timeline** of swimlanes — one per camera/subject/event-type
  combination actually present in history — with a histogram above it, hover preview,
  and click-through into the grid filtered to that lane and hour.

Both cards ship a visual editor, so every instance, camera, profile and filter is
picked from a dropdown or checklist rather than hand-typed as a uuid.
- **Media source** — PurrView recordings appear in the HA media browser, organised
  By camera / By subject / By type / Recent.
- **Services** — `purrview.flag_event` and `purrview.pin_event`, plus
  `purrview.start_recording` and `purrview.stop_recording` for recording a camera
  with no rule behind it.

## Requirements

- Home Assistant **2026.8** or newer.
- A reachable PurrView instance with an **API token** generated under
  Settings → Security.

HTTP is the default. Tick **Connect over HTTPS** in the config flow for a PurrView
behind TLS, and untick **Verify the certificate** only if that certificate is
self-signed — it applies to this integration's requests alone, never to the rest of
Home Assistant.

If PurrView later starts refusing the token, the integration raises a repair prompt
to re-enter it; the entry, and every card pointed at it, survives.

> **This integration authenticates with the API token, never the web-UI login
> password.** The two are independent switches in PurrView, and turning on *either*
> gates the whole app — so an install that sets only a password will lock this
> integration out. Generate an API token as well and paste it into the config flow.

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋮ → **Custom repositories**.
2. Add `https://github.com/cobryan05/purrview_ha` with category **Integration**.
3. Install **PurrView**, then restart Home Assistant.
4. Settings → Devices & Services → **Add Integration** → *PurrView*.

### Manual

Copy `custom_components/purrview/` into your Home Assistant `config/custom_components/`
directory and restart.

## Card options

Both cards are added from the **Add card** picker and configured in its visual
editor. The YAML underneath, if you prefer to write it:

```yaml
type: custom:purrview-card
entry_id: <purrview config entry id>   # required
profile_uuid: <watch profile uuid>     # required
source_uuid: <camera uuid>             # optional, defaults to the profile's first
```

```yaml
type: custom:purrview-events-card
entry_id: <purrview config entry id>   # required
title: Events                          # optional
page_size: 60                          # optional
max_height: 480                        # optional, px before the card scrolls internally
default_range: 7d                      # optional: today | 7d | 30d | all
default_source_uuids: []               # optional, preset camera filter
default_subject_refs: []               # optional, preset subject filter
default_rule_uuids: []                 # optional, preset event-type filter
```

The `default_*` filters are also what **Reset filters** returns to, not just the
starting state — a dashboard built for one camera snaps back to that camera.

## Development

```bash
pip install -r requirements_test.txt
pytest tests/
```

`pytest-homeassistant-custom-component` (pinned in `requirements_test.txt`) requires
**Python 3.14**. Tests use HA's own `hass` and `aioclient_mock` fixtures — no manual
`aiohttp` patching.

The cards' JavaScript has no automated suite; it is verified by hand against a
disposable Home Assistant instance. `tests/test_card_label_tree_mirror.py` is the
exception — it asserts the card's label tree still matches the app's, because the two
have no build step sharing them and divergence fails silently.

## License

Copyright 2026 Chris OBryan

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) and
[NOTICE](NOTICE). You may obtain a copy of the License at
<http://www.apache.org/licenses/LICENSE-2.0>.

Unless required by applicable law or agreed to in writing, software distributed
under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied.
