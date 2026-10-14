/**
 * Turning a failed call into something a card can show.
 *
 * `hass.callApi` rejects with a plain `{error, status_code, body}` object rather than
 * an Error, so `.message` is undefined on it and a template literal renders the whole
 * thing as "[object Object]" - losing both the status and the reason string the view
 * put there.
 */
export function errorText(err) {
  if (!err) return 'unknown error';
  if (typeof err === 'string') return err;

  const body = err.body;
  const detail =
    (body && (body.message || body.error || body.detail)) ||
    err.message ||
    err.error ||
    (err.status_code ? `HTTP ${err.status_code}` : null);

  if (!detail) return JSON.stringify(err);
  if (err.status_code && !String(detail).includes(String(err.status_code))) {
    return `${detail} (HTTP ${err.status_code})`;
  }
  return String(detail);
}
