/* Bidding Player — auto-updating engine loader.
 *
 * Publishers embed THIS file instead of pinning a specific engine version.
 * It reads the release channel manifest (engine/channel.json), resolves the
 * engine version to load (stable, with optional canary % rollout), then
 * injects the pinned engine script — copying through every data-* attribute
 * from this loader tag. The `__VER__` token in any attribute value (e.g. in
 * data-prebid-url) is replaced with the resolved `vX.Y.Z`.
 *
 * Why a loader instead of a jsDelivr semver range: the manifest gives an
 * instant, one-line ROLLBACK (point `stable` back a version + purge) and a
 * CANARY rollout — neither of which a bare `@2`/`@2.4` range can do.
 *
 * Channel control (optional, on the embed tag):
 *   data-channel="stable"  (default) — latest stable, with canary % rollout
 *   data-channel="canary"            — force the canary version (for QA)
 */
(function () {
  var REPO = "shashwatsilverpush/bidding-player";
  var CDN = "https://cdn.jsdelivr.net/gh/" + REPO;
  var MANIFEST = CDN + "@main/engine/channel.json";
  // Known-good engine used if the manifest can't be reached. Bump on release
  // only when the engine itself changes in a way the loader must floor to.
  var FALLBACK = "2.6.0";
  var TIMEOUT_MS = 1500;

  var me = document.currentScript || document.getElementById("adtech-player-core");
  if (!me) { (window.console || {}).warn && console.warn("[AdTechLoader] no anchor script found."); return; }

  function pickVersion(m) {
    try {
      var ch = (me.getAttribute("data-channel") || "stable").toLowerCase();
      if (ch === "canary" && m.canary) return m.canary;
      var stable = m.stable || FALLBACK;
      var pct = +m.canaryPct || 0;
      if (m.canary && pct > 0) {
        // Sticky per-browser bucket so a viewer stays on one version across loads.
        var key = "atp_canary_bucket", b = null;
        try { b = localStorage.getItem(key); if (b === null) { b = String(Math.floor(Math.random() * 100)); localStorage.setItem(key, b); } } catch (_) { b = String(Math.floor(Math.random() * 100)); }
        if (+b < pct) return m.canary;
      }
      return stable;
    } catch (_) { return FALLBACK; }
  }

  var booted = false;
  function boot(version) {
    if (booted) return;
    booted = true;
    var s = document.createElement("script");
    for (var i = 0; i < me.attributes.length; i++) {
      var a = me.attributes[i];
      if (a.name === "src" || a.name === "id" || a.name === "data-channel") continue;
      // Substitute the resolved version anywhere a __VER__ token appears.
      s.setAttribute(a.name, a.value.split("__VER__").join("v" + version));
    }
    s.id = "adtech-player-core";
    s.async = true;
    s.src = CDN + "@v" + version + "/engine/player.js";
    // Free the canonical id so the engine (which falls back to
    // getElementById when document.currentScript is null for injected
    // scripts) resolves to the engine tag, not this loader tag.
    me.removeAttribute("id");
    if (me.parentNode) me.parentNode.insertBefore(s, me.nextSibling);
    else (document.body || document.documentElement).appendChild(s);
  }

  try {
    var ctrl = ("AbortController" in window) ? new AbortController() : null;
    var to = setTimeout(function () { if (ctrl) try { ctrl.abort(); } catch (_) {} boot(FALLBACK); }, TIMEOUT_MS);
    var opts = ctrl ? { signal: ctrl.signal } : {};
    window.fetch(MANIFEST, opts)
      .then(function (r) { return r && r.ok ? r.json() : null; })
      .then(function (m) { clearTimeout(to); boot(m ? pickVersion(m) : FALLBACK); })
      .catch(function () { clearTimeout(to); boot(FALLBACK); });
  } catch (_) { boot(FALLBACK); }
})();
