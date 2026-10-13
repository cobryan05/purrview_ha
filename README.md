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
  draws a toggleable overlay of detections, tracks, zones, and labels. Ships a visual
  editor, so you pick the instance and camera from dropdowns.
- **Events card** (`purrview-events-card`) — browse recorded events with filters
  (subject label tree, date range), play clips and timelapses inline, flag an event
  for review, and pin it against cleanup.
- **Media source** — PurrView recordings appear in the HA media browser, organised
  By camera / By subject / By type / Recent.
- **Services** — `purrview.flag_event`, plus starting and stopping a manual recording.

## Requirements

- Home Assistant **2026.8** or newer.
- A reachable PurrView instance with an **API token** generated under
  Settings → Security.

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
