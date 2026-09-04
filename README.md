# PurrView for Home Assistant

A HACS integration that brings [PurrView](../whiskerwatcher) stats, live camera
views, and recorded events into Home Assistant. The Lovelace overlay card ships from
inside this same integration rather than as a separate HACS plugin (see
`custom_components/purrview/www/` once WP-5 lands).

Design rationale and the full work breakdown live in the main PurrView repo, not here:

- `../whiskerwatcher/HOME_ASSISTANT_PLAN.md` - why, and the trade-offs
- `../whiskerwatcher/HA_INTEGRATION_PLAN.md` - what to build, in what order

This repo only exists to hold the code for components B (integration) and C (card) of
that plan. Component A (the MQTT bridge) lives in the main PurrView repo itself.

## Status

WP-4 (this repo's own work): config flow, the media proxy view (`proxy.py`,
`Range`/`206`-aware, streams recordings/snapshots/crops through HA), the PurrView API
client (`api.py`), and the `media_source` browse tree (`media_source.py` - By camera /
By subject / By type / Recent, down to individual events) are all in and tested. Still
open: the `purrview.flag_event` service (WP-4 step 4) and the Lovelace card (WP-5).

On the main app side, WP-1 (flag backend), WP-2 (MQTT bridge + discovery, since widened
well past its original spec), WP-3 (auth token, widened into an optional web-UI login
too), and WP-6 (per-rule HA opt-out) are all done. See `HA_INTEGRATION_PLAN.md` for
current status on every work package.

## Development

Targets Home Assistant 2026.8+. `pytest-homeassistant-custom-component` 0.13.342 (the
version pinned below) requires **Python 3.14** — that's what pulled it in, not a choice
made independently of HA's own version support. It resolves to HA core 2026.7.0b2, a
beta of an earlier minor than the "2026.8+" target above — worth reverifying against a
2026.8 release before relying on any API surface used here that's new since 2026.7.

```bash
pip install -r requirements_test.txt
pytest tests/
```

Verified working as of this writing (`python:3.14-slim`, 36 tests green).

## Before publishing

- `manifest.json`'s `codeowners`, `documentation`, and `issue_tracker` are placeholders
  ("CHANGEME") - fill in once this has a real GitHub home.
- `LICENSE` is Apache-2.0. The PurrView application is licensed separately; the
  two are independent, and neither covers the other.
