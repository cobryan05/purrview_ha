/**
 * A tiny, self-contained fix for a "Configuration error" on purrview-card /
 * purrview-events-card that never clears, however many times the page is reloaded
 * or the app is restarted.
 *
 * The two real cards load via a bare `import()` in the HTML `add_extra_js_url`
 * injects - Home Assistant's own frontend bundles get a `<link rel="modulepreload">`
 * hint in that same HTML, ours don't, so on a bad enough connection they can queue
 * behind those much larger bundles long past the point Lovelace has already
 * rendered the dashboard and permanently given up on a card type it didn't
 * recognize yet. There is no API to make Lovelace re-check once a card finally
 * registers.
 *
 * A first attempt put this exact check at the bottom of each card's own module -
 * which only ever runs once that (large) file has *already* won its own load race.
 * On a connection bad enough to lose that race outright rather than merely delay it
 * (confirmed: Android app WebView, consistently, vs. a real mobile browser on the
 * same phone/network which does not), the embedded healer never got a chance to run
 * either - explaining "always stuck, restarting the app doesn't help." This file is
 * deliberately tiny (no card logic, no imports) so it wins that race independently:
 * whatever is starving the big card files should not be able to starve a script
 * this small too.
 */
setTimeout(() => {
  function deepQueryAll(root, selector, out) {
    out = out || [];
    if (root.querySelectorAll) for (const el of root.querySelectorAll(selector)) out.push(el);
    const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (const el of all) if (el.shadowRoot) deepQueryAll(el.shadowRoot, selector, out);
    return out;
  }
  const GUARD_KEY = 'purrview_ha_config_error_reload';
  if (deepQueryAll(document, 'hui-error-card').length === 0) {
    // Healthy - clear a guard a *previous* successful heal may have left behind, so
    // a genuinely later, independent race can still trigger its own retry.
    sessionStorage.removeItem(GUARD_KEY);
    return;
  }
  if (sessionStorage.getItem(GUARD_KEY)) {
    // Already retried once this navigation and it is still broken - a real,
    // unrelated configuration error (someone's bad YAML on another card), not our
    // load race. Cleared rather than left set, for the same reason as above.
    sessionStorage.removeItem(GUARD_KEY);
    return;
  }
  sessionStorage.setItem(GUARD_KEY, '1');
  location.reload();
}, 2000);
