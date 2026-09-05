/**
 * Events grid card (WP-5): a filter bar plus a grid of event thumbnails, backed by
 * PurrViewEventsView/PurrViewEventFacetsView. This is the flat alternative to HA's
 * own media_source browser (media_source.py) - that tree is fine for casting a clip
 * to a TV, but drilling through camera -> rule -> day for "what happened today" is
 * the wrong shape for a dashboard glance. This card asks the same backend
 * (/api/watch-events) for one filtered, flat page instead.
 *
 * Config:
 *   type: custom:purrview-events-card
 *   entry_id: <the purrview config entry id>   (required)
 *   title: <string>                             (optional, default "Events")
 *   page_size: <number>                         (optional, default 60)
 *
 * No visual editor yet - entry_id is the only required field and there is exactly
 * one thing to pick (mirrors how purrview-card.js's editor exists only because it
 * has a second, non-obvious field to choose from a live list).
 */

const DAY_MS = 24 * 60 * 60 * 1000;
const DEFAULT_PAGE_SIZE = 60;

//: Each option computes its own `startFrom` at click time, not at card-load time -
//: a card left open across midnight must not keep serving yesterday's "Today".
const RANGE_OPTIONS = [
  { value: 'today', label: 'Today', startFrom: () => new Date(new Date().setHours(0, 0, 0, 0)) },
  { value: '7d', label: 'Last 7 days', startFrom: () => new Date(Date.now() - 7 * DAY_MS) },
  { value: '30d', label: 'Last 30 days', startFrom: () => new Date(Date.now() - 30 * DAY_MS) },
  { value: 'all', label: 'All time', startFrom: () => null },
];

const STYLE = `
  :host { display: block; }
  ha-card { padding: 12px 12px 16px; }
  .title { font-size: 1.2em; font-weight: 500; padding: 0 4px 8px; }
  .filters {
    display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; align-items: center;
  }
  .filters select {
    font-size: 0.85em; padding: 6px 8px; border-radius: 6px;
    border: 1px solid var(--divider-color); background: var(--card-background-color);
    color: var(--primary-text-color);
  }
  .filters ha-selector { flex: 1 1 150px; min-width: 130px; max-width: 220px; }
  .reset {
    font-size: 0.85em; padding: 6px 10px; border-radius: 6px; cursor: pointer;
    border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color);
  }
  .views { display: flex; gap: 4px; margin-bottom: 10px; }
  .view-btn {
    font-size: 0.85em; padding: 6px 12px; border-radius: 6px; cursor: pointer;
    border: 1px solid var(--divider-color); background: transparent; color: var(--secondary-text-color);
  }
  .view-btn.active { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .status { padding: 8px 4px; color: var(--secondary-text-color); font-size: 0.9em; }
  .status--error { color: var(--error-color, #db4437); }
  .grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px;
  }
  .day-header {
    grid-column: 1 / -1; font-size: 0.85em; font-weight: 500; color: var(--secondary-text-color);
    padding: 10px 2px 4px; border-bottom: 1px solid var(--divider-color);
  }
  .day-header:first-child { padding-top: 0; }
  .tile {
    cursor: pointer; border: none; padding: 0; background: none; text-align: left;
    border-radius: 8px; overflow: hidden; background: var(--secondary-background-color, #222);
  }
  .tile img {
    display: block; width: 100%; aspect-ratio: 4 / 3; object-fit: cover; background: #111;
  }
  .tile .no-thumb {
    display: flex; align-items: center; justify-content: center; aspect-ratio: 4 / 3;
    color: #888; font-size: 0.8em; background: #111;
  }
  /* [hidden] and a plain class/tag selector are equal-or-lower specificity, but an
     author stylesheet's normal rule always outranks the UA sheet's [hidden] rule
     regardless of specificity - so without this, toggling the *property* had no
     visible effect and the thumbnail rendered stacked under "No image" forever
     (same bug purrview-card.js's own .placeholder[hidden] override exists for). */
  .tile img[hidden], .tile .no-thumb[hidden] { display: none; }
  .tile .caption { padding: 6px 8px; font-size: 0.78em; line-height: 1.3; }
  .tile .who { font-weight: 500; color: var(--primary-text-color); }
  .tile .meta { color: var(--secondary-text-color); display: block; }
  .tile .when { color: var(--secondary-text-color); display: block; }
  .tile .badge {
    font-size: 0.7em; padding: 1px 6px; border-radius: 999px; margin-left: 4px;
    background: var(--warning-color, #ff9800); color: #000;
  }
  .load-more { display: block; margin: 14px auto 0; padding: 8px 16px; }
  .empty { padding: 24px 4px; text-align: center; color: var(--secondary-text-color); }

  .lightbox {
    position: fixed; inset: 0; background: rgba(0, 0, 0, 0.85); z-index: 1000;
    display: flex; align-items: center; justify-content: center; padding: 24px;
  }
  .lightbox[hidden] { display: none; }
  .lightbox-inner { max-width: 900px; width: 100%; background: var(--card-background-color); border-radius: 8px; overflow: hidden; }
  .lightbox video, .lightbox img { display: block; width: 100%; max-height: 70vh; background: #000; }
  .lightbox-caption { padding: 10px 14px; font-size: 0.9em; color: var(--primary-text-color); display: flex; justify-content: space-between; align-items: center; }
  .lightbox-close { cursor: pointer; background: none; border: none; font-size: 1.3em; color: var(--primary-text-color); }

  /* ---- timeline: one swimlane per subject/rule, plain absolutely-positioned marks
     inside a shared-grid label|track layout - same visual language as the app's own
     events timeline (nvr/events/timeline.js), no canvas or SVG. ---- */
  .tl-body { overflow-x: auto; }
  .tl-row {
    display: grid; grid-template-columns: minmax(6rem, 14ch) 1fr; align-items: center;
    min-height: 30px; column-gap: 8px;
  }
  .tl-axis { min-height: 20px; margin-bottom: 4px; }
  .tl-label { display: flex; flex-direction: column; font-size: 0.78em; padding: 2px 0; overflow: hidden; }
  .tl-lane-name { color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tl-lane-count { color: var(--secondary-text-color); }
  .tl-track { position: relative; height: 22px; }
  .tl-axis .tl-track { height: 16px; }
  .tl-gridline { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--divider-color); }
  .tl-tick-label {
    position: absolute; top: 0; font-size: 0.7em; color: var(--secondary-text-color);
    transform: translateX(2px); white-space: nowrap;
  }
  .tl-mark {
    position: absolute; top: 2px; bottom: 2px; min-width: 3px; border: none; border-radius: 2px;
    background: var(--primary-color, #03a9f4); cursor: pointer; padding: 0;
  }
  .tl-mark:hover { outline: 1px solid var(--primary-text-color); }
`;

function fmtWhen(iso) {
  if (!iso) return '?';
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
  if (Number.isNaN(d.getTime())) return '?';
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return sameDay ? time : `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${time}`;
}

function clipRecordingUuid(event) {
  const rec = (event.recordings || []).find((r) => r.kind === 'clip' && r.status === 'complete');
  return rec ? rec.uuid : null;
}

function parseEventDate(iso) {
  if (!iso) return null;
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

function dayKey(iso) {
  const d = parseEventDate(iso);
  return d ? d.toDateString() : 'unknown';
}

function dayLabel(iso) {
  const d = parseEventDate(iso);
  if (!d) return 'Unknown date';
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return 'Today';
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return d.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' });
}

//: bucketStart is UTC-naive per WatchEventHistogramBucket's own docstring - always
//: append 'Z' before parsing, the same convention fmtWhen/parseEventDate use.
function parseBucketStart(bucketStart) {
  return Date.parse(`${bucketStart}Z`);
}

//: Folds a groups/histogram row down to the timeline's lane identity: one lane per
//: subject when there is one, else one lane per rule - a household cares "what did
//: Kitty do" more than "which camera," so camera/target are deliberately folded away
//: here (mirrors the app's own default identity grain before a viewer splits further).
function laneKeyFor(row) {
  if (row.subjectRef) return `subject:${row.subjectRef}`;
  if (row.ruleUuid) return `rule:${row.ruleUuid}`;
  return 'unknown';
}

function laneLabelFor(row) {
  return row.subjectName || row.ruleName || 'Unknown';
}

//: Local-midnight tick marks covering [start, end] - the timeline's only gridlines.
//: Sub-day ticks are deliberately left out: this is a dashboard glance, not a
//: scrubbable recorder timeline (STREAM_WATCHER_PLAN.md is explicit that no such
//: continuous timeline exists anywhere in this app).
function dayTicks(start, end) {
  const ticks = [];
  const d = new Date(start);
  d.setHours(0, 0, 0, 0);
  if (d.getTime() < start) d.setDate(d.getDate() + 1);
  while (d.getTime() <= end) {
    ticks.push(d.getTime());
    d.setDate(d.getDate() + 1);
  }
  if (!ticks.length) ticks.push(start);
  return ticks;
}

/**
 * A plain `<img src>`/`<video src>` sends no Authorization header, so a
 * `requires_auth` view like proxy.py's 401s it outright - the frame data on the live
 * view card sidesteps this by fetching JSON through `hass.callApi` (which does attach
 * the header) and decoding it into a blob, but that's not practical for a grid of N
 * thumbnails. The signed-path scheme HA's own media browser uses for thumbnails is
 * the documented way around this for a raw element `src`: a short-lived signature
 * appended as a query param, which the same auth middleware accepts in place of a
 * header (see proxy.py's own docstring - this is the frontend half of that).
 */
async function signPath(hass, path, expires) {
  try {
    const result = await hass.callWS({ type: 'auth/sign_path', path, expires });
    return result.path;
  } catch {
    return null;
  }
}

class PurrviewEventsCard extends HTMLElement {
  setConfig(config) {
    if (!config?.entry_id) throw new Error('purrview-events-card: "entry_id" is required');
    this._config = config;
    this._pageSize = config.page_size || DEFAULT_PAGE_SIZE;
    this._filters = { source_uuids: [], subject_refs: [], rule_uuids: [], range: '7d' };
    this._events = [];
    this._total = 0;
    this._view = 'grid';
    if (!this._built) this._build();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    // ha-selector renders nothing useful without a live .hass - same requirement
    // the config editor's entrySelector has (see PurrviewEventsCardEditor below).
    if (this._els) {
      this._els.sourceSelect.hass = hass;
      this._els.subjectSelect.hass = hass;
      this._els.ruleSelect.hass = hass;
    }
    if (first) this._init();
  }

  getCardSize() {
    return 6;
  }

  static getConfigElement() {
    return document.createElement('purrview-events-card-editor');
  }

  static async getStubConfig(hass) {
    // Mirrors purrview-card.js's getStubConfig: a fresh "Add Card" pick should just
    // work for the common single-instance household with no editing at all.
    try {
      const entries = await hass.callWS({ type: 'config_entries/get' });
      const entry = entries.find((e) => e.domain === 'purrview');
      return entry ? { type: 'custom:purrview-events-card', entry_id: entry.entry_id } : { type: 'custom:purrview-events-card' };
    } catch {
      return { type: 'custom:purrview-events-card' };
    }
  }

  connectedCallback() {
    this._connected = true;
  }

  disconnectedCallback() {
    this._connected = false;
  }

  async _init() {
    await this._loadFacets();
    await this._loadEvents({ reset: true });
  }

  _build() {
    const root = this.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = STYLE;

    const card = document.createElement('ha-card');

    const title = document.createElement('div');
    title.className = 'title';
    title.textContent = this._config.title || 'Events';
    title.hidden = !this._config.title && false; // always show a title, default "Events"

    const filters = document.createElement('div');
    filters.className = 'filters';

    const sourceSelect = this._makeMultiSelect('source_uuids', 'Camera');
    const subjectSelect = this._makeMultiSelect('subject_refs', 'Subject');
    const ruleSelect = this._makeMultiSelect('rule_uuids', 'Event type');
    const rangeSelect = document.createElement('select');
    for (const opt of RANGE_OPTIONS) {
      const o = document.createElement('option');
      o.value = opt.value;
      o.textContent = opt.label;
      rangeSelect.appendChild(o);
    }
    rangeSelect.value = this._filters.range;
    rangeSelect.addEventListener('change', () => {
      this._filters.range = rangeSelect.value;
      this._clearDrillDown();
      this._reload();
    });

    const reset = document.createElement('button');
    reset.className = 'reset';
    reset.textContent = 'Reset filters';
    reset.addEventListener('click', () => this._resetFilters());

    filters.append(sourceSelect, subjectSelect, ruleSelect, rangeSelect, reset);

    const views = document.createElement('div');
    views.className = 'views';
    const viewGridBtn = document.createElement('button');
    viewGridBtn.className = 'view-btn';
    viewGridBtn.textContent = 'Grid';
    viewGridBtn.addEventListener('click', () => this._setView('grid'));
    const viewTimelineBtn = document.createElement('button');
    viewTimelineBtn.className = 'view-btn';
    viewTimelineBtn.textContent = 'Timeline';
    viewTimelineBtn.addEventListener('click', () => this._setView('timeline'));
    views.append(viewGridBtn, viewTimelineBtn);

    const status = document.createElement('div');
    status.className = 'status';
    status.textContent = 'Loading…';

    const gridWrap = document.createElement('div');
    const grid = document.createElement('div');
    grid.className = 'grid';
    const loadMore = document.createElement('button');
    loadMore.className = 'load-more';
    loadMore.textContent = 'Load more';
    loadMore.hidden = true;
    loadMore.addEventListener('click', () => this._loadEvents({ reset: false }));
    gridWrap.append(grid, loadMore);

    const timelineWrap = document.createElement('div');
    timelineWrap.hidden = true;
    const timelineBody = document.createElement('div');
    timelineBody.className = 'tl-body';
    timelineWrap.appendChild(timelineBody);

    card.append(title, filters, views, status, gridWrap, timelineWrap);

    const lightbox = document.createElement('div');
    lightbox.className = 'lightbox';
    lightbox.hidden = true;
    lightbox.addEventListener('click', (ev) => {
      if (ev.target === lightbox) this._closeLightbox();
    });
    root.append(style, card, lightbox);

    this._els = {
      title,
      sourceSelect,
      subjectSelect,
      ruleSelect,
      rangeSelect,
      status,
      gridWrap,
      grid,
      loadMore,
      timelineWrap,
      timelineBody,
      viewGridBtn,
      viewTimelineBtn,
      lightbox,
    };
    this._setView('grid');
  }

  //: A `ha-selector` (`select`, `multiple: true`) rather than a native
  //: `<select multiple>` - the platform multi-select needs ctrl/cmd-click to pick
  //: more than one option, which nothing in this UI hints at; HA's own selector
  //: renders checkboxes/chips instead, the same component the config editor already
  //: uses for entry_id (see PurrviewEventsCardEditor._build below).
  _makeMultiSelect(field, label) {
    const selector = document.createElement('ha-selector');
    selector.selector = { select: { multiple: true, mode: 'dropdown', options: [] } };
    selector.label = label;
    selector.value = [];
    selector.addEventListener('value-changed', (ev) => {
      ev.stopPropagation();
      this._filters[field] = ev.detail.value || [];
      this._clearDrillDown();
      this._reload();
    });
    this._built = true;
    return selector;
  }

  _resetFilters() {
    this._filters = { source_uuids: [], subject_refs: [], rule_uuids: [], range: '7d' };
    for (const key of ['sourceSelect', 'subjectSelect', 'ruleSelect']) this._els[key].value = [];
    this._els.rangeSelect.value = '7d';
    this._clearDrillDown();
    this._reload();
  }

  //: A timeline mark click narrows the filter bar to an exact [start, end) window
  //: that no RANGE_OPTIONS preset can express - cleared whenever the viewer touches
  //: a filter control themselves, so a stale drill-down window never silently
  //: outlives the click that created it.
  _clearDrillDown() {
    delete this._filters.explicitStart;
    delete this._filters.explicitEnd;
  }

  _setView(view) {
    this._view = view;
    this._els.gridWrap.hidden = view !== 'grid';
    this._els.timelineWrap.hidden = view !== 'timeline';
    this._els.viewGridBtn.classList.toggle('active', view === 'grid');
    this._els.viewTimelineBtn.classList.toggle('active', view === 'timeline');
    if (view === 'timeline') this._loadTimeline();
  }

  _reload() {
    if (this._view === 'timeline') this._loadTimeline();
    else this._loadEvents({ reset: true });
  }

  _filterParams() {
    const params = new URLSearchParams();
    for (const field of ['source_uuids', 'subject_refs', 'rule_uuids']) {
      for (const value of this._filters[field] || []) params.append(field, value);
    }
    if (this._filters.explicitStart) {
      params.set('start_from', this._filters.explicitStart);
      if (this._filters.explicitEnd) params.set('start_to', this._filters.explicitEnd);
    } else {
      const rangeOpt = RANGE_OPTIONS.find((o) => o.value === this._filters.range);
      const startFrom = rangeOpt?.startFrom();
      if (startFrom) params.set('start_from', startFrom.toISOString());
    }
    return params;
  }

  async _loadFacets() {
    try {
      const facets = await this._hass.callApi('GET', `purrview/${this._config.entry_id}/event-facets`);
      this._fillOptions(this._els.sourceSelect, facets?.sources || []);
      this._fillOptions(this._els.subjectSelect, facets?.subjects || []);
      this._fillOptions(this._els.ruleSelect, facets?.rules || []);
      // The event payload itself carries ruleName but only sourceUuid, not a camera
      // name (WatchEventRead has no source_name field) - facets is the only place
      // that name lives, so the tile caption looks it up from here.
      this._sourceNames = Object.fromEntries((facets?.sources || []).map((s) => [s.ref, s.name]));
    } catch (err) {
      this._setStatus(`Could not load filters. (${err.message || err})`, true);
    }
  }

  _fillOptions(selector, options) {
    const current = selector.value || [];
    selector.selector = {
      select: { multiple: true, mode: 'dropdown', options: options.map((o) => ({ value: o.ref, label: o.name })) },
    };
    selector.value = current;
  }

  async _loadEvents({ reset }) {
    if (this._loading) return;
    this._loading = true;
    if (reset) {
      this._events = [];
      this._els.grid.innerHTML = '';
      // Tracks the day header of the last tile appended, so "load more" continuing
      // an existing day doesn't repeat its header, but a fresh reset always starts
      // clean even if the next page happens to open on the same day as before.
      this._lastSectionDay = null;
    }
    this._setStatus('Loading…');
    this._els.loadMore.hidden = true;

    try {
      const params = this._filterParams();
      params.set('limit', String(this._pageSize));
      params.set('offset', String(this._events.length));

      const data = await this._hass.callApi('GET', `purrview/${this._config.entry_id}/events?${params.toString()}`);
      const page = data?.events || [];
      this._total = data?.total ?? this._events.length + page.length;
      this._events = this._events.concat(page);

      for (const event of page) {
        const day = dayKey(event.startedAt);
        if (day !== this._lastSectionDay) {
          this._els.grid.appendChild(this._sectionHeader(dayLabel(event.startedAt)));
          this._lastSectionDay = day;
        }
        this._els.grid.appendChild(this._tile(event));
      }

      this._els.loadMore.hidden = this._events.length >= this._total;
      this._setStatus(this._events.length ? '' : '', false);
      if (!this._events.length) {
        const empty = document.createElement('div');
        empty.className = 'empty';
        empty.textContent = 'No events match these filters.';
        this._els.grid.appendChild(empty);
      }
    } catch (err) {
      this._setStatus(`Could not reach PurrView. (${err.message || err})`, true);
    } finally {
      this._loading = false;
    }
  }

  _sectionHeader(label) {
    const header = document.createElement('div');
    header.className = 'day-header';
    header.textContent = label;
    return header;
  }

  async _loadTimeline() {
    if (this._loadingTimeline) return;
    this._loadingTimeline = true;
    this._setStatus('Loading…');

    try {
      const params = this._filterParams();
      const [groupsData, histData] = await Promise.all([
        this._hass.callApi('GET', `purrview/${this._config.entry_id}/event-groups?${params.toString()}`),
        this._hass.callApi(
          'GET',
          `purrview/${this._config.entry_id}/event-histogram?bucket=hour&${params.toString()}`
        ),
      ]);
      this._renderTimeline(groupsData?.groups || [], histData?.bucket || 'hour', histData?.buckets || []);
      this._setStatus('');
    } catch (err) {
      this._setStatus(`Could not reach PurrView. (${err.message || err})`, true);
    } finally {
      this._loadingTimeline = false;
    }
  }

  //: Explicit range filters compute their own start; "All time" has none to compute,
  //: so the axis falls back to the data's own extent (widened to a 7-day floor when
  //: there is no data at all, so an empty account doesn't render a zero-width axis).
  //: Also remembered as `_timelineQueryStart` for `_drillDown` - the first bucket of
  //: a windowed range is a *partial* hour (its count only covers events after this
  //: exact cutoff, not the whole UTC hour), and a drill-down that blindly re-queries
  //: the full hour would silently pull in extra events from before the filter.
  _timelineRange(buckets, bucketMs) {
    const rangeOpt = RANGE_OPTIONS.find((o) => o.value === this._filters.range);
    const explicitStart = rangeOpt?.startFrom();
    const end = Date.now();
    this._timelineQueryStart = explicitStart ? explicitStart.getTime() : null;
    if (explicitStart) return { start: explicitStart.getTime(), end };
    if (!buckets.length) return { start: end - 7 * DAY_MS, end };
    const starts = buckets.map((b) => parseBucketStart(b.bucketStart));
    return { start: Math.min(...starts), end: Math.max(...starts) + bucketMs };
  }

  _renderTimeline(groups, bucket, buckets) {
    const bucketMs = bucket === 'day' ? DAY_MS : 60 * 60 * 1000;
    const { start, end } = this._timelineRange(buckets, bucketMs);
    const span = Math.max(end - start, 1);

    // Fold both responses down to one row per lane: groups gives each lane its
    // label/total, histogram gives each lane its marks - joined on the same
    // subject-else-rule key so a mark never has to guess which lane it belongs to.
    const lanes = new Map();
    for (const g of groups) {
      const key = laneKeyFor(g);
      const lane = lanes.get(key) || {
        key,
        label: laneLabelFor(g),
        count: 0,
        marks: new Map(),
        subjectRef: g.subjectRef || null,
        ruleUuid: g.subjectRef ? null : g.ruleUuid || null,
      };
      lane.count += g.count || 0;
      lanes.set(key, lane);
    }
    for (const b of buckets) {
      const lane = lanes.get(laneKeyFor(b));
      if (!lane) continue;
      const t = parseBucketStart(b.bucketStart);
      lane.marks.set(t, (lane.marks.get(t) || 0) + (b.count || 0));
    }
    const laneList = [...lanes.values()].sort((a, b) => b.count - a.count);

    const body = this._els.timelineBody;
    body.innerHTML = '';

    if (!laneList.length) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = 'No events match these filters.';
      body.appendChild(empty);
      return;
    }

    const peak = Math.max(1, ...laneList.flatMap((l) => [...l.marks.values()]));
    const ticks = dayTicks(start, end);
    body.appendChild(this._timelineAxisRow(ticks, start, span));
    for (const lane of laneList) body.appendChild(this._timelineLaneRow(lane, ticks, start, span, peak, bucketMs));
  }

  _timelineAxisRow(ticks, start, span) {
    const row = document.createElement('div');
    row.className = 'tl-row tl-axis';
    const label = document.createElement('div');
    label.className = 'tl-label';
    const track = document.createElement('div');
    track.className = 'tl-track';
    for (const t of ticks) {
      const pct = ((t - start) / span) * 100;
      const line = document.createElement('div');
      line.className = 'tl-gridline';
      line.style.left = `${pct}%`;
      const tickLabel = document.createElement('span');
      tickLabel.className = 'tl-tick-label';
      tickLabel.style.left = `${pct}%`;
      tickLabel.textContent = new Date(t).toLocaleDateString([], { month: 'short', day: 'numeric' });
      track.append(line, tickLabel);
    }
    row.append(label, track);
    return row;
  }

  _timelineLaneRow(lane, ticks, start, span, peak, bucketMs) {
    const row = document.createElement('div');
    row.className = 'tl-row';

    const label = document.createElement('div');
    label.className = 'tl-label';
    const name = document.createElement('span');
    name.className = 'tl-lane-name';
    name.textContent = lane.label;
    const count = document.createElement('span');
    count.className = 'tl-lane-count';
    count.textContent = `${lane.count} event${lane.count === 1 ? '' : 's'}`;
    label.append(name, count);

    const track = document.createElement('div');
    track.className = 'tl-track';
    for (const t of ticks) {
      const line = document.createElement('div');
      line.className = 'tl-gridline';
      line.style.left = `${((t - start) / span) * 100}%`;
      track.appendChild(line);
    }
    for (const [t, markCount] of lane.marks) {
      const mark = document.createElement('button');
      mark.className = 'tl-mark';
      mark.style.left = `${((t - start) / span) * 100}%`;
      mark.style.width = `${Math.max((bucketMs / span) * 100, 0.6)}%`;
      mark.style.opacity = String(0.35 + 0.65 * (markCount / peak));
      const when = new Date(t).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      mark.title = `${lane.label} — ${markCount} event${markCount === 1 ? '' : 's'} — ${when}`;
      mark.addEventListener('click', () => this._drillDown(lane, t, bucketMs));
      track.appendChild(mark);
    }

    row.append(label, track);
    return row;
  }

  //: Jumps to the grid, pre-filtered to this lane and narrowed to exactly the
  //: clicked bucket's window - the timeline's only form of "drill down," since
  //: there is no separate modal here (unlike the app's own hover-preview + click-to-
  //: expand-in-place, which needs a canvas-free page's worth of extra machinery this
  //: card's dashboard-glance scope doesn't warrant).
  _drillDown(lane, bucketStartMs, bucketMs) {
    // The first bucket of a windowed range is partial (see _timelineRange) - clamp
    // up to the range's real cutoff so this doesn't pull in events from before it.
    const clampedStart = Math.max(bucketStartMs, this._timelineQueryStart ?? -Infinity);
    this._filters.subject_refs = lane.subjectRef ? [lane.subjectRef] : [];
    this._filters.rule_uuids = !lane.subjectRef && lane.ruleUuid ? [lane.ruleUuid] : [];
    this._filters.explicitStart = new Date(clampedStart).toISOString();
    this._filters.explicitEnd = new Date(bucketStartMs + bucketMs).toISOString();
    this._els.subjectSelect.value = this._filters.subject_refs;
    this._els.ruleSelect.value = this._filters.rule_uuids;
    this._setView('grid');
    this._loadEvents({ reset: true });
  }

  _tile(event) {
    const tile = document.createElement('button');
    tile.className = 'tile';

    if (event.hasSnapshot || event.hasCrop) {
      const img = document.createElement('img');
      const kind = event.hasCrop ? 'crop' : 'snapshot';
      img.loading = 'lazy';
      img.alt = event.subjectName || event.ruleName || 'Event';
      img.hidden = true;
      const placeholder = document.createElement('div');
      placeholder.className = 'no-thumb';
      placeholder.textContent = 'No image';
      tile.append(img, placeholder);
      signPath(this._hass, `/api/purrview/${this._config.entry_id}/${kind}/${event.uuid}`, 60).then((signed) => {
        if (!signed) return;
        img.src = signed;
        img.hidden = false;
        placeholder.hidden = true;
      });
    } else {
      const placeholder = document.createElement('div');
      placeholder.className = 'no-thumb';
      placeholder.textContent = 'No image';
      tile.appendChild(placeholder);
    }

    const caption = document.createElement('div');
    caption.className = 'caption';

    const who = document.createElement('span');
    who.className = 'who';
    who.textContent = event.subjectName || event.eventLabel || 'Unknown';
    caption.appendChild(who);
    if (event.reviewState === 'flagged') {
      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.textContent = 'flagged';
      caption.appendChild(badge);
    }

    // Rule and camera, when known - subject alone doesn't say *why* this was
    // recorded or *where*, and a household with more than one camera or rule needs
    // both to tell same-subject events apart at a glance.
    const cameraName = this._sourceNames?.[event.sourceUuid];
    const metaParts = [event.ruleName, cameraName].filter(Boolean);
    if (metaParts.length) {
      const meta = document.createElement('span');
      meta.className = 'meta';
      meta.textContent = metaParts.join(' · ');
      caption.appendChild(meta);
    }

    const when = document.createElement('span');
    when.className = 'when';
    when.textContent = fmtWhen(event.startedAt);
    caption.appendChild(when);
    tile.appendChild(caption);

    tile.addEventListener('click', () => this._openLightbox(event));
    return tile;
  }

  async _openLightbox(event) {
    const { lightbox } = this._els;
    lightbox.innerHTML = '';
    // Bumped on every open/close - a slow sign_path round trip from a click the
    // viewer already moved on from must not paste stale media into whatever the
    // lightbox is showing (or not showing) by the time it resolves.
    const token = (this._lightboxToken = (this._lightboxToken || 0) + 1);

    const inner = document.createElement('div');
    inner.className = 'lightbox-inner';

    const recordingUuid = clipRecordingUuid(event);
    if (recordingUuid) {
      // 300s, not the grid thumbnail's 60s - a clip can run longer than that between
      // opening the lightbox and finishing playback, and a scrub past that point would
      // otherwise re-request the (by-then-expired) signed URL.
      const signed = await signPath(
        this._hass,
        `/api/purrview/${this._config.entry_id}/recording/${recordingUuid}`,
        300
      );
      if (signed && token === this._lightboxToken) {
        const video = document.createElement('video');
        video.controls = true;
        video.autoplay = true;
        video.src = signed;
        inner.appendChild(video);
      }
    } else if (event.hasSnapshot || event.hasCrop) {
      const kind = event.hasCrop ? 'crop' : 'snapshot';
      const signed = await signPath(this._hass, `/api/purrview/${this._config.entry_id}/${kind}/${event.uuid}`, 60);
      if (signed && token === this._lightboxToken) {
        const img = document.createElement('img');
        img.src = signed;
        inner.appendChild(img);
      }
    }
    if (token !== this._lightboxToken) return;

    const caption = document.createElement('div');
    caption.className = 'lightbox-caption';
    const label = document.createElement('span');
    const who = event.subjectName || event.eventLabel || 'Unknown';
    const cameraName = this._sourceNames?.[event.sourceUuid];
    const rest = [event.ruleName, cameraName, fmtWhen(event.startedAt)].filter(Boolean).join(' — ');
    label.textContent = `${who} — ${rest}`;
    const close = document.createElement('button');
    close.className = 'lightbox-close';
    close.textContent = '✕';
    close.addEventListener('click', () => this._closeLightbox());
    caption.append(label, close);
    inner.appendChild(caption);

    lightbox.appendChild(inner);
    lightbox.hidden = false;
  }

  _closeLightbox() {
    this._lightboxToken = (this._lightboxToken || 0) + 1;
    const { lightbox } = this._els;
    const video = lightbox.querySelector('video');
    if (video) video.pause();
    lightbox.hidden = true;
    lightbox.innerHTML = '';
  }

  _setStatus(text, isError) {
    const { status } = this._els;
    status.textContent = text;
    status.hidden = !text;
    status.classList.toggle('status--error', Boolean(isError));
  }
}

customElements.define('purrview-events-card', PurrviewEventsCard);

const EDITOR_STYLE = `
  .row { margin-bottom: 12px; }
  label { display: block; font-size: 0.85em; margin-bottom: 4px; color: var(--secondary-text-color); }
  input[type="text"] { width: 100%; padding: 8px; font-size: 0.9em; border-radius: 4px; box-sizing: border-box; }
`;

/**
 * Config editor for purrview-events-card: an entry picker (HA's generic
 * <ha-selector config_entry>, same shape purrview-card.js's editor uses) plus an
 * optional title field. No profile/camera picker here - unlike the live view card,
 * this one has nothing per-camera to choose; the filter bar itself is the camera
 * picker, at view time rather than config time.
 */
class PurrviewEventsCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    if (this._built) this._sync();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._els.entrySelector.hass = hass;
    this._sync();
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
      this._updateConfig({ entry_id: ev.detail.value });
    });
    entryRow.append(entryLabel, entrySelector);

    const titleRow = document.createElement('div');
    titleRow.className = 'row';
    const titleLabel = document.createElement('label');
    titleLabel.textContent = 'Title (optional)';
    const titleInput = document.createElement('input');
    titleInput.type = 'text';
    titleInput.placeholder = 'Events';
    titleInput.addEventListener('change', () => {
      this._updateConfig({ title: titleInput.value || undefined });
    });
    titleRow.append(titleLabel, titleInput);

    root.append(style, entryRow, titleRow);
    this._els = { entrySelector, titleInput };
    this._built = true;
  }

  _sync() {
    this._els.entrySelector.value = this._config?.entry_id;
    if (document.activeElement !== this._els.titleInput) {
      this._els.titleInput.value = this._config?.title || '';
    }
  }

  _updateConfig(patch) {
    this._config = { ...this._config, ...patch };
    for (const key of Object.keys(this._config)) {
      if (this._config[key] === undefined) delete this._config[key];
    }
    this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: this._config }, bubbles: true, composed: true }));
  }
}

customElements.define('purrview-events-card-editor', PurrviewEventsCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'purrview-events-card',
  name: 'PurrView Events',
  description: 'A filterable grid of recorded PurrView events, with click-to-play.',
});
