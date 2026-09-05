/**
 * Live view card (WP-5): polls PurrViewLivePreviewView through the entry's proxy,
 * draws the frame plus a toggleable detection/track/zone overlay.
 *
 * Config:
 *   type: custom:purrview-card
 *   entry_id: <the purrview config entry id>   (required - see the URL in
 *     Settings > Devices & services > PurrView > a hub card, "...#config_entry=…")
 *   profile_uuid: <watch profile uuid>          (required)
 *   source_uuid: <camera uuid>                  (optional - defaults to the
 *     profile's first camera; a <select> lets the viewer switch if the profile
 *     watches more than one)
 *
 * Has a visual editor (PurrviewCardEditor below) - entry_id, profile_uuid and
 * source_uuid are all picked from dropdowns (backed by PurrViewWatchProfilesView and
 * PurrViewProfileSourcesView respectively), not hand-typed. A profile can outlive
 * any one running task_uuid (restarts, redeploys), which is why this polls by
 * profile_uuid and lets PurrViewClient.get_live_preview resolve the current task
 * server-side (see HA_INTEGRATION_PLAN.md WP-5) rather than the card tracking a
 * task_uuid itself.
 */

import {
  DETECTION_COLOUR,
  boxColour,
  decodeFrame,
  drawBox,
  isEventTrack,
  labelText,
  overlayScale,
  scaleBox,
  trackColour,
  ZONE_COLOUR,
} from './purrview-overlay.js';

const POLL_INTERVAL_MS = 1000;

const STYLE = `
  :host { display: block; }
  ha-card { overflow: hidden; }
  .wrap { position: relative; background: #111; }
  canvas { display: block; width: 100%; height: auto; background: #111; }
  .status {
    padding: 6px 12px; font-size: 0.85em; color: var(--secondary-text-color);
    border-top: 1px solid var(--divider-color);
  }
  .status--error { color: var(--error-color, #db4437); }
  .controls {
    display: flex; flex-wrap: wrap; gap: 4px 14px; align-items: center;
    padding: 6px 12px; border-bottom: 1px solid var(--divider-color);
  }
  .controls label { display: flex; align-items: center; gap: 4px; font-size: 0.85em; cursor: pointer; }
  select { font-size: 0.85em; }
  .placeholder {
    display: flex; align-items: center; justify-content: center; color: #888;
    aspect-ratio: 16 / 9; font-size: 0.9em;
  }
  /* [hidden] and a plain class selector are equal specificity, and this stylesheet's
     own .placeholder rule above comes after the UA sheet's [hidden] rule in the
     cascade - so without this, setting the hidden *property* had no visible effect
     and the "Waiting for a frame..." placeholder stayed on screen under the canvas
     forever, found live rather than in review. */
  .placeholder[hidden] { display: none; }
`;

class PurrviewCard extends HTMLElement {
  setConfig(config) {
    if (!config?.entry_id) throw new Error('purrview-card: "entry_id" is required');
    if (!config?.profile_uuid) throw new Error('purrview-card: "profile_uuid" is required');
    this._config = config;
    this._sourceUuid = config.source_uuid || null;
    this._sinceSeq = null;
    this._show = { detections: true, tracks: true, zones: true, labels: true };
    if (!this._built) this._build();
  }

  set hass(hass) {
    this._hass = hass;
    this._maybeStartPolling();
  }

  getCardSize() {
    return 6;
  }

  static getConfigElement() {
    return document.createElement('purrview-card-editor');
  }

  static async getStubConfig(hass) {
    // Best-effort: a fresh "Add Card" pick should just work for the common
    // single-instance, single-camera household with no editing at all. Any
    // failure here (no entries yet, PurrView unreachable) falls back to an
    // incomplete config - setConfig's own validation then guides the viewer to
    // the editor's dropdowns instead of leaving them looking at a blank card.
    try {
      const entries = await hass.callWS({ type: 'config_entries/get' });
      const entry = entries.find((e) => e.domain === 'purrview');
      if (!entry) return { type: 'custom:purrview-card' };

      const data = await hass.callApi('GET', `purrview/${entry.entry_id}/watch-profiles`);
      const profiles = data?.profiles ?? [];
      const profile = profiles.find((p) => p.live) ?? profiles[0];
      if (!profile) return { type: 'custom:purrview-card', entry_id: entry.entry_id };

      return { type: 'custom:purrview-card', entry_id: entry.entry_id, profile_uuid: profile.uuid };
    } catch {
      return { type: 'custom:purrview-card' };
    }
  }

  connectedCallback() {
    this._connected = true;
    this._maybeStartPolling();
  }

  disconnectedCallback() {
    this._connected = false;
    this._stopPolling();
  }

  _build() {
    const root = this.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = STYLE;

    const card = document.createElement('ha-card');
    const wrap = document.createElement('div');
    wrap.className = 'wrap';

    const canvas = document.createElement('canvas');
    canvas.hidden = true;
    const placeholder = document.createElement('div');
    placeholder.className = 'placeholder';
    placeholder.textContent = 'Waiting for a frame…';
    wrap.append(canvas, placeholder);

    const status = document.createElement('div');
    status.className = 'status';
    status.textContent = 'Connecting…';

    const controls = document.createElement('div');
    controls.className = 'controls';
    const sourceSelect = document.createElement('select');
    sourceSelect.hidden = true;
    sourceSelect.addEventListener('change', () => {
      this._sourceUuid = sourceSelect.value;
      this._sinceSeq = null;
      // Nothing else clears `_image` between here and the next successful apply -
      // without this, a slow-cadence source (Ring/ring-mqtt in particular, tens of
      // seconds between real snapshots) kept showing the *previous* camera's photo
      // under the new selection for however long that gap turned out to be.
      this._image = null;
      this._preview = null;
      this._draw();
      this._poll({ immediate: true });
    });
    controls.appendChild(sourceSelect);

    for (const [key, label] of [
      ['detections', 'Detections'],
      ['tracks', 'Tracks'],
      ['zones', 'Zones'],
      ['labels', 'Labels'],
    ]) {
      const wrapper = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = this._show[key];
      input.addEventListener('change', () => {
        this._show[key] = input.checked;
        this._draw();
      });
      wrapper.append(input, document.createTextNode(label));
      controls.appendChild(wrapper);
    }

    card.append(controls, wrap, status);
    root.append(style, card);

    this._els = { canvas, placeholder, status, controls, sourceSelect, card };
    this._ctx = canvas.getContext('2d');
    this._built = true;
  }

  _maybeStartPolling() {
    if (!this._built || !this._hass || !this._connected || this._polling) return;
    this._polling = true;
    this._poll({ immediate: true });
  }

  _stopPolling() {
    this._polling = false;
    if (this._pollTimer) clearTimeout(this._pollTimer);
  }

  _scheduleNext() {
    if (!this._polling) return;
    this._pollTimer = setTimeout(() => this._poll(), POLL_INTERVAL_MS);
  }

  async _poll({ immediate = false } = {}) {
    if (!this._polling) return;
    // A hidden tab (dashboard not in view) still owns this element - no reason to
    // keep decoding JPEGs nobody is looking at. Same guard the app's own NVR pane
    // uses (skipWhileHidden).
    if (document.hidden && !immediate) {
      this._scheduleNext();
      return;
    }
    if (this._inFlight) {
      // A switch mid-flight must not sit out the rest of the normal 1s cadence on
      // top of whatever's left of the current request - that's exactly the delay
      // that left the previous camera's photo on screen. Remembered instead, and
      // fired the moment the in-flight request clears, rather than scheduled here.
      if (immediate) this._pendingImmediate = true;
      else this._scheduleNext();
      return;
    }
    this._inFlight = true;
    try {
      const params = new URLSearchParams({ profile_uuid: this._config.profile_uuid });
      if (this._sourceUuid) params.set('source_uuid', this._sourceUuid);
      if (this._sinceSeq != null) params.set('since_seq', String(this._sinceSeq));

      const data = await this._hass.callApi(
        'GET',
        `purrview/${this._config.entry_id}/live-preview?${params.toString()}`
      );
      const preview = data?.preview;
      if (!preview) {
        this._setStatus('This watcher is not running.', true);
        this._preview = null;
      } else {
        await this._apply(preview);
      }
    } catch (err) {
      this._setStatus(`Could not reach PurrView — retrying. (${err.message || err})`, true);
    } finally {
      this._inFlight = false;
      if (this._pendingImmediate) {
        this._pendingImmediate = false;
        this._poll({ immediate: true });
      } else {
        this._scheduleNext();
      }
    }
  }

  async _apply(preview) {
    this._syncSources(preview.sources ?? []);

    if (preview.frame) {
      const { decode } = decodeFrame(preview.frame);
      try {
        this._image = await decode();
      } catch {
        this._image = null;
      }
      this._sinceSeq = preview.frameSeq ?? null;
    } else if (!preview.frameUnchanged) {
      this._image = null;
      this._sinceSeq = null;
    } else {
      this._sinceSeq = preview.frameSeq ?? this._sinceSeq;
    }

    this._preview = preview;
    this._draw();
    this._renderStatus(preview);
  }

  _syncSources(sources) {
    const select = this._els.sourceSelect;
    if (sources.length < 2) {
      select.hidden = true;
      return;
    }
    select.hidden = false;
    const currentOptions = [...select.options].map((o) => o.value);
    const wantOptions = sources.map((s) => s.sourceUuid);
    if (currentOptions.join(',') !== wantOptions.join(',')) {
      select.innerHTML = '';
      for (const s of sources) {
        const opt = document.createElement('option');
        opt.value = s.sourceUuid;
        opt.textContent = s.sourceName || s.sourceUuid;
        select.appendChild(opt);
      }
    }
    if (!this._sourceUuid) this._sourceUuid = sources[0]?.sourceUuid ?? null;
    select.value = this._sourceUuid ?? '';
  }

  _draw() {
    const preview = this._preview;
    const { canvas, placeholder } = this._els;
    if (!preview) {
      canvas.hidden = true;
      placeholder.hidden = false;
      return;
    }

    const width = preview.frameWidth || canvas.width || 640;
    const height = preview.frameHeight || canvas.height || 360;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    canvas.hidden = false;
    placeholder.hidden = true;

    const ctx = this._ctx;
    ctx.clearRect(0, 0, width, height);
    if (this._image) {
      ctx.drawImage(this._image, 0, 0, width, height);
    } else {
      ctx.fillStyle = '#111';
      ctx.fillRect(0, 0, width, height);
    }

    const k = overlayScale(preview);
    const pen = { lineWidth: 2 * k, fontPx: 12 * k };

    if (this._show.zones) {
      for (const zone of preview.zones ?? []) this._drawZone(zone, width, height, pen);
    }
    if (this._show.detections) {
      for (const det of preview.detections ?? []) {
        drawBox(
          ctx,
          scaleBox(det.bbox, k),
          boxColour(det, DETECTION_COLOUR),
          this._show.labels ? `${labelText(det.labelName, det.labelUuid, 'det')} ${(det.confidence ?? 0).toFixed(2)}` : null,
          { dashed: true, ...pen }
        );
      }
    }
    if (this._show.tracks) {
      for (const track of preview.tracks ?? []) {
        const rules = track.eventRules ?? [];
        const active = isEventTrack(track);
        const status = trackColour(track);
        const colour = boxColour(track, status);
        const caption = [
          `#${track.trackId}`,
          labelText(track.labelName, track.labelUuid, ''),
          track.confidence != null ? track.confidence.toFixed(2) : '',
          active ? `● ${rules.join(', ')}` : '',
        ]
          .filter(Boolean)
          .join(' ');
        drawBox(ctx, scaleBox(track.bbox, k), colour, this._show.labels ? caption : null, {
          emphasis: active,
          glow: active || track.isAnchor ? status : null,
          ...pen,
        });
      }
    }
  }

  _drawZone(zone, width, height, { lineWidth = 2, fontPx = 12 } = {}) {
    const points = (zone.points ?? []).map(([x, y]) => [x * width, y * height]);
    if (points.length < 2) return;
    const ctx = this._ctx;
    ctx.save();
    ctx.strokeStyle = ZONE_COLOUR;
    ctx.lineWidth = lineWidth;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(points[0][0], points[0][1]);
    for (const [x, y] of points.slice(1)) ctx.lineTo(x, y);
    ctx.closePath();
    ctx.stroke();
    if (this._show.labels && zone.name) {
      ctx.setLineDash([]);
      ctx.fillStyle = ZONE_COLOUR;
      ctx.font = `${fontPx}px sans-serif`;
      ctx.fillText(zone.name, points[0][0] + 3, points[0][1] + fontPx + 1);
    }
    ctx.restore();
  }

  _renderStatus(preview) {
    const age = preview.frameAgeS;
    const dueIn = preview.frameDueInS;
    const overdue = dueIn != null ? dueIn <= 0 : age != null && preview.analysisFps && age > Math.max(5, 5 / preview.analysisFps);
    const failing = preview.sourceState === 'failed' || preview.sourceState === 'reconnecting';
    const stale = overdue || failing;
    const dueSuffix = dueIn != null && dueIn > 0 ? ` Next frame due in ${Math.round(dueIn)}s.` : '';
    const buffer = preview.buffer ? ` — ${preview.buffer}` : '';

    const text = preview.lastError
      ? `Source error: ${preview.lastError}`
      : stale
        ? `No new frame for ${age}s — the source may be down.`
        : preview.sourceState === 'connecting'
          ? `Connecting to the source…${dueSuffix}`
          : preview.dryRun
            ? `Watching (dry run — no actions will fire).${dueSuffix}${buffer}`
            : `Watching.${dueSuffix}${buffer}`;

    this._setStatus(text, Boolean(preview.lastError) || stale);
  }

  _setStatus(text, isError) {
    const { status } = this._els;
    status.textContent = text;
    status.classList.toggle('status--error', Boolean(isError));
  }
}

customElements.define('purrview-card', PurrviewCard);

const EDITOR_STYLE = `
  .row { margin-bottom: 12px; }
  label { display: block; font-size: 0.85em; margin-bottom: 4px; color: var(--secondary-text-color); }
  select { width: 100%; padding: 8px; font-size: 0.9em; border-radius: 4px; }
`;

/**
 * Config editor for purrview-card: two dropdowns (PurrView instance, camera/watcher)
 * instead of hand-typed entry_id/profile_uuid. The instance dropdown is HA's own
 * generic <ha-selector> with a `config_entry` selector (the same selector shape
 * services.yaml uses for purrview.flag_event) - it already knows how to list and
 * label config entries, so this doesn't re-implement that. The profile dropdown has
 * no such built-in selector (there's no HA concept of "watch profile"), so it's
 * populated by hand from PurrViewWatchProfilesView.
 */
class PurrviewCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    // Editing an existing card (entry_id/profile_uuid already set) needs its
    // dropdowns populated immediately, not just on the next entry-picker change -
    // hass is already set by the time HA calls setConfig on a re-opened editor.
    if (this._built) {
      this._maybeLoadProfiles();
      this._maybeLoadSources();
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._els.entrySelector.hass = hass;
    this._maybeLoadProfiles();
    this._maybeLoadSources();
  }

  connectedCallback() {
    if (this._built) this._renderProfileOptions();
  }

  _build() {
    const root = this.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = EDITOR_STYLE;

    const entryRow = document.createElement('div');
    entryRow.className = 'row';
    const entryLabel = document.createElement('label');
    entryLabel.textContent = 'PurrView instance';
    const entrySelector = document.createElement('ha-selector');
    entrySelector.selector = { config_entry: { integration: 'purrview' } };
    entrySelector.addEventListener('value-changed', (ev) => {
      ev.stopPropagation();
      this._loadedFor = undefined;
      this._updateConfig({ entry_id: ev.detail.value, profile_uuid: undefined });
      this._maybeLoadProfiles();
    });
    entryRow.append(entryLabel, entrySelector);

    const profileRow = document.createElement('div');
    profileRow.className = 'row';
    const profileLabel = document.createElement('label');
    profileLabel.textContent = 'Camera / watcher';
    const profileSelect = document.createElement('select');
    profileSelect.addEventListener('change', () => {
      // A source_uuid picked for the old profile isn't meaningful once the profile
      // itself changes - it may not even watch that camera.
      this._sourcesLoadedFor = undefined;
      this._updateConfig({ profile_uuid: profileSelect.value || undefined, source_uuid: undefined });
      this._maybeLoadSources();
    });
    profileRow.append(profileLabel, profileSelect);

    const sourceRow = document.createElement('div');
    sourceRow.className = 'row';
    const sourceLabel = document.createElement('label');
    sourceLabel.textContent = 'Default camera (optional)';
    const sourceSelect = document.createElement('select');
    sourceSelect.addEventListener('change', () => {
      this._updateConfig({ source_uuid: sourceSelect.value || undefined });
    });
    sourceRow.append(sourceLabel, sourceSelect);

    root.append(style, entryRow, profileRow, sourceRow);
    this._els = { entrySelector, profileSelect, sourceSelect };
    this._built = true;
  }

  _updateConfig(patch) {
    this._config = { ...this._config, ...patch };
    for (const key of Object.keys(this._config)) {
      if (this._config[key] === undefined) delete this._config[key];
    }
    this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: this._config }, bubbles: true, composed: true }));
    this._renderProfileOptions();
    this._renderSourceOptions();
  }

  async _maybeLoadProfiles() {
    if (!this._built) return;
    this._els.entrySelector.value = this._config?.entry_id;
    const entryId = this._config?.entry_id;
    if (!entryId) {
      this._profiles = [];
      this._renderProfileOptions();
      return;
    }
    if (this._loadedFor === entryId) {
      this._renderProfileOptions();
      return;
    }
    this._loadedFor = entryId;
    this._els.profileSelect.disabled = true;
    try {
      const data = await this._hass.callApi('GET', `purrview/${entryId}/watch-profiles`);
      this._profiles = data?.profiles ?? [];
    } catch {
      this._profiles = [];
    }
    this._els.profileSelect.disabled = false;
    this._renderProfileOptions();
  }

  _renderProfileOptions() {
    if (!this._built) return;
    const select = this._els.profileSelect;
    const profiles = this._profiles ?? [];

    select.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = profiles.length ? 'Select a camera/watcher…' : 'No watch profiles found';
    select.appendChild(placeholder);
    for (const profile of profiles) {
      const opt = document.createElement('option');
      opt.value = profile.uuid;
      opt.textContent = profile.live ? `${profile.name} (live)` : profile.name;
      select.appendChild(opt);
    }
    select.value = this._config?.profile_uuid || '';
  }

  //: A profile's *configured* cameras (PurrViewProfileSourcesView, backed by
  //: WatchProfileRead.sources), not get_live_preview's `sources` list - that one
  //: only exists while the watcher happens to be running, and editing the card is a
  //: perfectly normal thing to do while it isn't.
  async _maybeLoadSources() {
    if (!this._built) return;
    const entryId = this._config?.entry_id;
    const profileUuid = this._config?.profile_uuid;
    if (!entryId || !profileUuid) {
      this._sources = [];
      this._renderSourceOptions();
      return;
    }
    const cacheKey = `${entryId}/${profileUuid}`;
    if (this._sourcesLoadedFor === cacheKey) {
      this._renderSourceOptions();
      return;
    }
    this._sourcesLoadedFor = cacheKey;
    this._els.sourceSelect.disabled = true;
    try {
      const data = await this._hass.callApi('GET', `purrview/${entryId}/watch-profiles/${profileUuid}/sources`);
      this._sources = data?.sources ?? [];
    } catch {
      this._sources = [];
    }
    this._els.sourceSelect.disabled = false;
    this._renderSourceOptions();
  }

  _renderSourceOptions() {
    if (!this._built) return;
    const select = this._els.sourceSelect;
    const sources = this._sources ?? [];

    select.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = this._config?.profile_uuid
      ? sources.length
        ? 'First camera (default)'
        : 'No cameras found for this watcher'
      : 'Pick a camera/watcher first';
    select.appendChild(placeholder);
    for (const source of sources) {
      const opt = document.createElement('option');
      opt.value = source.uuid;
      opt.textContent = source.name;
      select.appendChild(opt);
    }
    select.value = this._config?.source_uuid || '';
  }
}

customElements.define('purrview-card-editor', PurrviewCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'purrview-card',
  name: 'PurrView Live View',
  description: 'Live camera view with a toggleable detection overlay, from a PurrView watcher.',
});

// The stuck-"Configuration error" self-heal used to live here, but a copy embedded
// in this same module can only run once this (large, slow-loading) file has already
// won its own load race - on a connection bad enough to lose that race outright
// (rather than just delay it), the healer never got a chance to run either. It now
// lives in its own tiny file, purrview-heal.js, registered alongside this one so it
// can win that race independently. See that file for the full reasoning.
