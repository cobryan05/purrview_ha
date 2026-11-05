/**
 * Overlay drawing conventions, ported from PurrView's own
 * apps/image_tagging_server/static/js/app/nvr/overlay.js (+ the scaling helpers
 * from liveViewModal.js) rather than reinvented: normalised coordinates and
 * analysis-space scaling are easy to get subtly wrong.
 *
 * This card has no build step and can't import across the app/HACS boundary, so
 * this is a copy, not a shared module - keep it in sync by hand if the source ever
 * changes shape. Colours, box/caption drawing and the detection/track distinction
 * (dashed vs solid) are unchanged from the source; only the module wrapper and the
 * card-specific colour re-export below are new.
 */

export const DETECTION_COLOUR = '#ffb347';
export const TRACK_COLOUR = '#4ade80';
export const ANCHOR_COLOUR = '#60a5fa';
export const ZONE_COLOUR = '#c084fc';
export const EVENT_COLOUR = '#f87171';

export function labelText(labelName, labelUuid, fallback = '?') {
  if (labelName) return labelName;
  if (labelUuid) return `${labelUuid.slice(0, 8)}…`;
  return fallback;
}

export function isEventTrack(track) {
  return (track?.eventRules ?? []).length > 0;
}

export function trackColour(track) {
  if (isEventTrack(track)) return EVENT_COLOUR;
  return track?.isAnchor ? ANCHOR_COLOUR : TRACK_COLOUR;
}

export function isDrawableColour(value) {
  if (typeof value !== 'string') return false;
  const colour = value.trim();
  if (!colour) return false;
  if (/^#([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(colour)) return true;
  if (/^(rgb|rgba|hsl|hsla)\([^()]*\)$/i.test(colour)) return true;
  return /^[a-z]+$/i.test(colour);
}

export function boxColour(item, fallback) {
  return isDrawableColour(item?.labelColor) ? item.labelColor.trim() : fallback;
}

export function drawBox(ctx, bbox, colour, label, { dashed = false, emphasis = false, lineWidth = 2, fontPx = 12, glow = null, faded = false } = {}) {
  if (!ctx || !bbox || bbox.length !== 4) return;
  const [x1, y1, x2, y2] = bbox;
  ctx.save();
  if (faded) ctx.globalAlpha = 0.35;
  ctx.strokeStyle = colour;
  ctx.lineWidth = emphasis ? lineWidth * 2 : lineWidth;
  if (emphasis || glow) {
    ctx.shadowColor = glow ?? colour;
    ctx.shadowBlur = emphasis ? 12 : 8;
  }
  if (dashed) ctx.setLineDash([5, 4]);
  ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
  ctx.shadowBlur = 0;
  if (label) {
    ctx.setLineDash([]);
    ctx.font = `${fontPx}px sans-serif`;
    const metrics = ctx.measureText(label);
    const boxTop = Math.max(0, y1 - fontPx - 3);
    ctx.fillStyle = 'rgba(0,0,0,0.65)';
    ctx.fillRect(x1, boxTop, metrics.width + 6, fontPx + 2);
    ctx.fillStyle = colour;
    ctx.fillText(label, x1 + 3, boxTop + fontPx - 1);
  }
  ctx.restore();
}

export function decodeFrame(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const blob = new Blob([bytes], { type: 'image/jpeg' });
  return {
    blob,
    decode: async () => {
      const url = URL.createObjectURL(blob);
      try {
        const img = new Image();
        img.src = url;
        await img.decode();
        return img;
      } finally {
        URL.revokeObjectURL(url);
      }
    },
  };
}

/**
 * Pixels of served frame per pixel of analysed frame. 1 unless a full-resolution
 * frame is being shown: detections/tracks are always reported in *analysis* space,
 * so drawing them onto a full-res frame unscaled crams every box into the
 * top-left corner. This is the single most likely bug in this card - ported
 * verbatim from liveViewModal.js's overlayScale, not re-derived.
 */
export function overlayScale(preview) {
  const served = preview?.frameWidth;
  const analysed = preview?.analysisFrameWidth;
  if (!served || !analysed) return 1;
  return served / analysed;
}

export function scaleBox(bbox, k) {
  return k === 1 ? bbox : bbox.map((v) => v * k);
}
