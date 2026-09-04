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

Scaffolding only, on this side. Config flow (host/port/token, WP-4 step 1) is in place
and tested. Everything else here - media_source, the proxy view, the flag service, the
card - is not built yet.

On the main app side, WP-1 (flag backend), WP-2 (MQTT bridge + discovery, since widened
well past its original spec), and WP-6 (per-rule HA opt-out) are done. WP-3 (auth
token) is not built yet and blocks WP-4's proxy view. See `HA_INTEGRATION_PLAN.md` for
current status on every work package.

## Development

Targets Home Assistant 2026.8+. `pytest-homeassistant-custom-component` 0.13.342 (the
version pinned below) requires **Python 3.14** — that's what pulled it in, not a choice
made independently of HA's own version support.

```bash
pip install -r requirements_test.txt
pytest tests/
```

Verified working as of this writing (`python:3.14-slim`, both config flow tests green).

## Before publishing

- `manifest.json`'s `codeowners`, `documentation`, and `issue_tracker` are placeholders
  ("CHANGEME") - fill in once this has a real GitHub home.
- `LICENSE` is Apache-2.0. The PurrView application is licensed separately; the
  two are independent, and neither covers the other.
