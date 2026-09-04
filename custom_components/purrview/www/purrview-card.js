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
 * No card-config editor yet - YAML only. A profile can outlive any one running
 * task_uuid (restarts, redeploys), which is why this polls by profile_uuid and
 * lets PurrViewClient.get_live_preview resolve the current task server-side
 * (see HA_INTEGRATION_PLAN.md WP-5) rather than the card tracking a task_uuid
 * itself.
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
    padding: 6px 12px; border-top: 1px solid var(--divider-color);
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

    card.append(wrap, status, controls);
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
      this._scheduleNext();
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
      this._scheduleNext();
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

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'purrview-card',
  name: 'PurrView Live View',
  description: 'Live camera view with a toggleable detection overlay, from a PurrView watcher.',
});
