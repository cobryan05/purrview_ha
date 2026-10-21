/**
 * Draws a recorded clip's detections on a canvas over the `<video>`, from the JSON
 * sidecar PurrView writes beside the mp4 (`/api/recordings/{uuid}/overlay`).
 *
 * Nothing is composited into the video, so the toggle costs no round trip and the clip
 * HA plays is byte-identical to the one on disk.
 *
 * Ported from the app's own `nvr/events/clipOverlay.js` rather than reinvented - the
 * letterbox math and the measured playback lead below are both easy to get subtly
 * wrong, and both are invisible when wrong in a way that looks like a bad detector.
 * No build step crosses the app/HACS boundary, so this is a copy; keep it in step by
 * hand. What is dropped relative to the source: the app's custom control bar (this
 * keeps the native one) and the "save frame for annotation" hook (HA does no
 * annotation, by design).
 */

/** Sidecar shapes this understands. v2 only added keys to each track; nothing moved. */
const SUPPORTED_VERSIONS = new Set([1, 2]);

/** Fallback hold when a sidecar omits `maxStalenessS`. Generous, but still bounded. */
const DEFAULT_STALENESS_S = 1.5;

/** The "rule was firing" frame's thickness, in CSS pixels. */
const EVENT_FRAME_WIDTH = 4;

/** Box colour for a label with no colour of its own. */
const DEFAULT_BOX_COLOUR = '#38bdf8';

/** Colour of the frame marking the window the rule believed the event was in. */
const EVENT_COLOUR = '#ef4444';

/** Below this, a duration disagreement is muxer rounding, not an untrimmed head. */
const LEAD_FLOOR_S = 0.25;

/**
 * Where the picture actually is inside a letterboxed `<video>`, in CSS pixels relative
 * to the element's own box. The canvas covers the whole element, so skipping this draws
 * every box displaced by the letterbox bars.
 */
export function videoRect(video) {
  const boxW = video.clientWidth;
  const boxH = video.clientHeight;
  const natW = video.videoWidth;
  const natH = video.videoHeight;
  // Before metadata arrives there is no aspect ratio to honour; the first
  // `loadedmetadata` redraw fixes the one frame this gets wrong.
  if (!natW || !natH || !boxW || !boxH) return { left: 0, top: 0, width: boxW, height: boxH };
  const scale = Math.min(boxW / natW, boxH / natH);
  const width = natW * scale;
  const height = natH * scale;
  return { left: (boxW - width) / 2, top: (boxH - height) / 2, width, height };
}

/**
 * The sample in effect at `t` seconds into the clip, or null.
 *
 * Held until the next one, because the watcher analyses at a few frames a second while
 * the video plays at the camera's full rate - without the hold the boxes strobe. The
 * hold is bounded by the sidecar's own `maxStalenessS`: past that the watcher was not
 * analysing, and drawing nothing is honest where a frozen box invents a detection.
 */
export function sampleAt(doc, t) {
  const frames = doc?.frames || [];
  const maxStale = Number.isFinite(doc?.maxStalenessS) ? doc.maxStalenessS : DEFAULT_STALENESS_S;
  let found = null;
  for (const frame of frames) {
    if (frame.t > t) break;
    found = frame;
  }
  if (!found) return null;
  return t - found.t <= maxStale ? found : null;
}

/** Whether the rule was firing at `t`. Pre-roll and post-roll look like the event. */
export function eventActiveAt(doc, t) {
  const ev = doc?.event;
  if (!ev || !Number.isFinite(ev.startS)) return false;
  const end = Number.isFinite(ev.endS) ? ev.endS : Infinity;
  return t >= ev.startS && t <= end;
}

/**
 * Seconds of video that play *before* the sidecar's t=0, from the two durations.
 *
 * MediaMTX cannot cut at an arbitrary instant: a clip starts at the keyframe at or
 * before the one asked for and marks the excess with a negative PTS plus an mp4 edit
 * list - several seconds on real clips. Whether that head is *played* is up to the
 * browser, so it is measured rather than assumed: `declaredS` is how long the clip was
 * meant to be, `actualS` is how long this browser thinks it is, and a browser that
 * ignored the edit list reports the head as surplus length. That surplus IS the offset.
 *
 * Clamped at 0 in both directions that matter. A file *shorter* than declared is a
 * chunk-assembled clip whose duration was summed instead of measured - a different
 * fault that shifting would disguise - and a sub-`LEAD_FLOOR_S` surplus is the final
 * frame's own duration, which is noise.
 *
 * Declined outright for `partCount > 1`: `concat_parts` regenerates timestamps and
 * discards each part's edit list, so such a file plays *every* part's head in every
 * browser while `declaredS` is the sum of the logical spans - shifting by the surplus
 * would over-correct by N-1 heads on exactly the long events that path exists for.
 */
export function untrimmedLead(declaredS, actualS, partCount = 1) {
  const declared = Number(declaredS);
  const actual = Number(actualS);
  if (!Number.isFinite(declared) || !Number.isFinite(actual) || declared <= 0) return 0;
  if (Number(partCount) > 1) return 0;
  const surplus = actual - declared;
  return surplus > LEAD_FLOOR_S ? surplus : 0;
}

/** A sidecar document, or null if it is absent or a shape this cannot draw. */
export function parseOverlay(doc) {
  if (!doc || !SUPPORTED_VERSIONS.has(doc.version) || !Array.isArray(doc.frames)) return null;
  return doc;
}

/**
 * Attach an overlay canvas to a `<video>`.
 *
 * The canvas is a sibling inside a positioned wrapper, not drawn into the video: a
 * `<video>` cannot host children. It is `pointer-events: none`, so the native controls
 * underneath keep working.
 *
 * @param {HTMLVideoElement} video - must already be in the DOM
 * @param {Object} doc - a sidecar document from `parseOverlay`
 * @param {Object} [options]
 * @param {boolean} [options.visible=true]
 * @param {Map<string,string>} [options.labelColours] - labelUuid -> `#rrggbb`
 * @param {Document|ShadowRoot} [options.fullscreenRoot=document] - where to look up the
 *   current fullscreen element. A card lives in a shadow root, and `document`
 *   retargets `fullscreenElement` to the host, so the default cannot see the video.
 * @returns {{setVisible: (on: boolean) => void, redraw: () => void, destroy: () => void}}
 */
export function attachClipOverlay(video, doc, { visible = true, labelColours = new Map(), fullscreenRoot = document } = {}) {
  const wrapper = document.createElement('div');
  wrapper.className = 'clip-overlay';
  wrapper.style.position = 'relative';
  wrapper.style.display = 'block';
  wrapper.style.lineHeight = '0';
  video.parentNode.insertBefore(wrapper, video);
  wrapper.appendChild(video);

  const canvas = document.createElement('canvas');
  canvas.className = 'clip-overlay__canvas';
  canvas.style.position = 'absolute';
  canvas.style.left = '0';
  canvas.style.top = '0';
  canvas.style.pointerEvents = 'none';
  wrapper.appendChild(canvas);

  let showing = visible;
  let lead = 0;

  function measureLead() {
    lead = untrimmedLead(doc?.durationS, video.duration, doc?.partCount);
  }

  function draw() {
    const rect = videoRect(video);
    // Backed at device resolution so a 1px stroke is a real pixel on a HiDPI screen,
    // but laid out in CSS pixels - hence the transform rather than scaling every
    // coordinate at the call sites.
    const dpr = window.devicePixelRatio || 1;
    const cssW = video.clientWidth;
    const cssH = video.clientHeight;
    if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
    }
    canvas.style.width = `${cssW}px`;
    canvas.style.height = `${cssH}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);
    if (!showing) return;

    // Sidecar time, which equals player time only on a browser that honoured the clip's
    // edit list - see `untrimmedLead`.
    const t = (video.currentTime || 0) - lead;

    if (eventActiveAt(doc, t)) {
      ctx.strokeStyle = EVENT_COLOUR;
      ctx.lineWidth = EVENT_FRAME_WIDTH;
      ctx.strokeRect(
        rect.left + EVENT_FRAME_WIDTH / 2,
        rect.top + EVENT_FRAME_WIDTH / 2,
        Math.max(0, rect.width - EVENT_FRAME_WIDTH),
        Math.max(0, rect.height - EVENT_FRAME_WIDTH),
      );
      const name = doc.event?.ruleName;
      if (name) {
        drawTag(ctx, `● ${name}`, rect.left + EVENT_FRAME_WIDTH + 4, rect.top + EVENT_FRAME_WIDTH + 4, EVENT_COLOUR);
      }
    }

    const sample = sampleAt(doc, t);
    for (const box of sample?.boxes || []) {
      const colour = labelColours.get(box.labelUuid) || DEFAULT_BOX_COLOUR;
      const x = rect.left + box.x * rect.width;
      const y = rect.top + box.y * rect.height;
      const w = box.w * rect.width;
      const h = box.h * rect.height;
      ctx.strokeStyle = colour;
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, w, h);
      const label = box.conf ? `${box.label || '?'} ${Math.round(box.conf * 100)}%` : box.label || '?';
      drawTag(ctx, label, x, Math.max(rect.top, y - 16), colour);
    }
  }

  function drawTag(ctx, text, x, y, colour) {
    ctx.font = '12px system-ui, sans-serif';
    const width = ctx.measureText(text).width + 8;
    ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
    ctx.fillRect(x, y, width, 16);
    ctx.fillStyle = colour;
    ctx.fillText(text, x + 4, y + 12);
  }

  // `timeupdate` alone fires about four times a second, which visibly lags the picture.
  // `requestVideoFrameCallback` redraws in step with the frames actually presented where
  // it exists; the listeners stay regardless, so a paused, seeked or resized player
  // still updates - which rVFC does not cover.
  let rafHandle = null;
  function pump() {
    draw();
    if (video.requestVideoFrameCallback) rafHandle = video.requestVideoFrameCallback(pump);
  }
  if (video.requestVideoFrameCallback) rafHandle = video.requestVideoFrameCallback(pump);

  const redraw = () => draw();
  // The lead can only be measured once the browser knows the duration, and must be
  // measured before the first paint that uses it - hence its own handler.
  const onMetadata = () => {
    measureLead();
    draw();
  };
  measureLead();
  video.addEventListener('timeupdate', redraw);
  video.addEventListener('seeked', redraw);
  video.addEventListener('loadedmetadata', onMetadata);
  video.addEventListener('durationchange', onMetadata);

  /**
   * Keep the canvas on screen when something fullscreens the video.
   *
   * Only the fullscreen element's own subtree is painted, and the canvas is the video's
   * *sibling* - so the native control bar's fullscreen button, and a browser's own
   * double-click gesture, both show the picture with its boxes stripped off. The
   * request is promoted to the wrapper, which is the video's ancestor, so the picture
   * never leaves the screen on the way.
   *
   * Escalated rather than exited and re-entered: leaving fullscreen first spends the
   * gesture that opened it, and the second request is then refused for want of
   * transient activation. Gecko requires activation for every request and denies this
   * one, where the only honest outcome left is no fullscreen at all - so a refusal
   * exits, rather than leaving a picture missing its boxes.
   */
  const onFullscreenChange = () => {
    if (fullscreenRoot.fullscreenElement === video) {
      wrapper.requestFullscreen?.().catch(() => document.exitFullscreen?.());
      return;
    }
    redraw();
  };
  document.addEventListener('fullscreenchange', onFullscreenChange);

  const observer = new ResizeObserver(redraw);
  observer.observe(video);
  draw();

  return {
    setVisible(on) {
      showing = !!on;
      draw();
    },
    redraw,
    destroy() {
      observer.disconnect();
      video.removeEventListener('timeupdate', redraw);
      video.removeEventListener('seeked', redraw);
      video.removeEventListener('loadedmetadata', onMetadata);
      video.removeEventListener('durationchange', onMetadata);
      document.removeEventListener('fullscreenchange', onFullscreenChange);
      if (rafHandle != null && video.cancelVideoFrameCallback) video.cancelVideoFrameCallback(rafHandle);
      canvas.remove();
      // The video goes back where it was, so a caller holding a reference to it is not
      // left with a detached node.
      wrapper.parentNode?.insertBefore(video, wrapper);
      wrapper.remove();
    },
  };
}
