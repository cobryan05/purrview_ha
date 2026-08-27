# WhiskerWatcher for Home Assistant

A HACS integration that brings [WhiskerWatcher](../whiskerwatcher) stats, live camera
views, and recorded events into Home Assistant. The Lovelace overlay card ships from
inside this same integration rather than as a separate HACS plugin (see
`custom_components/whiskerwatcher/www/` once WP-5 lands).

Design rationale and the full work breakdown live in the WhiskerWatcher repo, not here:

- `../whiskerwatcher/HOME_ASSISTANT_PLAN.md` - why, and the trade-offs
- `../whiskerwatcher/HA_INTEGRATION_PLAN.md` - what to build, in what order

This repo only exists to hold the code for components B (integration) and C (card) of
that plan. Component A (the MQTT bridge) lives in the WhiskerWatcher repo itself.

## Status

Scaffolding only. Config flow (host/port/token, WP-4 step 1) is in place and tested.
Everything else - media_source, the proxy view, the flag service, the card - is not
built yet.

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
