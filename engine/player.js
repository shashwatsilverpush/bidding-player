(function () {
  // 1. DYNAMIC CONFIGURATION ACCEPTER
  var currentScript = document.currentScript || document.getElementById("adtech-player-core");
  
  if (!currentScript) {
    console.warn("[AdTechPlayer] Script element target missing anchor validation.");
    return;
  }

  var cfg = {
    // ─── Bidder configuration ─────────────────────────────────────
    // v2 (preferred): `data-bidders` is a JSON array of full Prebid bid
    // objects, e.g.
    //   data-bidders='[
    //     {"bidder":"limelightDigital","params":{"host":"...","publisherId":"...","adUnitId":972556929}},
    //     {"bidder":"appnexus","params":{"placementId":12345}}
    //   ]'
    // v1 legacy: `data-host` + `data-pub-id` + `data-adunit-id` are read as
    // shortcuts for a single-bidder limelightDigital config. Used as the
    // fallback when `data-bidders` is missing/empty/invalid so every existing
    // v1 tag in the wild keeps working unchanged.
    biddersJson: currentScript.getAttribute("data-bidders") || "",
    publisherId: currentScript.getAttribute("data-pub-id")  || "",
    adUnitId:    currentScript.getAttribute("data-adunit-id") || "",
    bidderHost:  currentScript.getAttribute("data-host")    || "ads-jbi003.rtba.bidsxchange.com",

    adTagUrl:    currentScript.getAttribute("data-tag") || "",
    timeout:     parseInt(currentScript.getAttribute("data-timeout"), 10) || 1200,
    // An explicit data-bias="0" (or "0.00") means "no strategic bias" and must
    // be honoured — a plain `|| 0.10` would wrongly coerce 0 back to the default.
    // A missing/invalid attribute still falls back to 0.10 so legacy v1 tags
    // (which never set data-bias) keep their original behaviour.
    floorBias:   (function (b) { return isNaN(b) ? 0.10 : b; })(parseFloat(currentScript.getAttribute("data-bias"))),
    // Floor min: bids below this CPM are rejected (treated as no-bid).
    // Floor max: winning CPM is capped at this value before bias + bucketing.
    // Both default to null (disabled) when the attribute is absent or non-numeric.
    floorMin:    (function (v) { return isNaN(v) ? null : v; })(parseFloat(currentScript.getAttribute("data-floor-min"))),
    floorMax:    (function (v) { return isNaN(v) ? null : v; })(parseFloat(currentScript.getAttribute("data-floor-max"))),
    // "instream" (default) plays the ad against a content video via IMA's
    // pause/resume flow. "outstream" has no content — the ad is the content:
    // the slot stays collapsed until it scrolls ≥50% into view, autoplays
    // muted, then collapses again on completion or error.
    placement:   (currentScript.getAttribute("data-placement") || "instream").toLowerCase(),
    // Sticky / floating-video: when the instream player scrolls out of view it
    // shrinks and docks to a screen corner (with a close button) so the video —
    // and any ad on it — keeps playing. Lifts viewability and completed views.
    sticky:      currentScript.getAttribute("data-sticky") === "true",
    videoUrl:    currentScript.getAttribute("data-video") || "",
    autoplay:    currentScript.getAttribute("data-autoplay") === "true",
    muted:       currentScript.getAttribute("data-muted") === "true",
    fluid:       currentScript.getAttribute("data-fluid") !== "false",
    loop:        currentScript.getAttribute("data-loop") === "true",
    preload:     currentScript.getAttribute("data-preload") || "metadata",
    vpaidMode:   currentScript.getAttribute("data-vpaid") || "insecure",
    divId:       currentScript.getAttribute("data-div-id") || "comparos-video-placement",
    cacheUrl:    currentScript.getAttribute("data-cache") || "https://prebid.adnxs.com/pbc/v1/cache",
    prebidUrl:   currentScript.getAttribute("data-prebid-url") || "https://cdnjs.cloudflare.com/ajax/libs/prebid.js/6.7.0/prebid.js",

    // ─── Telemetry (control-plane analytics) ──────────────────────
    // When data-beacon-url + data-account + data-placement-id are present, the
    // engine fire-and-forgets lifecycle events (load, bid request/response,
    // win, impression, complete, error) to the collector. Absent on legacy
    // tags → telemetry is a no-op, so nothing changes for existing publishers.
    account:     currentScript.getAttribute("data-account") || "",
    placementId: currentScript.getAttribute("data-placement-id") || "",
    beaconUrl:   currentScript.getAttribute("data-beacon-url") || "",
    sampleRate:  (function (v) { return isNaN(v) ? 1 : v; })(parseFloat(currentScript.getAttribute("data-sample-rate"))),

    // ─── Dynamic ("integrate-once") config ────────────────────────
    // When data-config-url is present (alongside data-placement-id), the engine
    // fetches RuntimeConfig from <config-url>/<placement-id> at boot and applies
    // it OVER these attribute defaults — so demand (DSP add/remove), floors,
    // bias, timeout and the VAST tag are backend-controlled and change with no
    // tag edit on the publisher's side. Absent → the tag is fully static (every
    // existing tag in the wild is unaffected).
    configUrl:   currentScript.getAttribute("data-config-url") || ""
  };

  // Resolve the bidder list for this auction. New tags use `data-bidders`
  // JSON; older tags fall through to the legacy single-bidder Limelight
  // shape built from data-host / data-pub-id / data-adunit-id. Either way,
  // the engine downstream just iterates `cfg.bidders`.
  function resolveBidders() {
    if (cfg.biddersJson) {
      try {
        var parsed = JSON.parse(cfg.biddersJson);
        if (Array.isArray(parsed) && parsed.length) return parsed;
        warn("data-bidders must be a non-empty JSON array; falling back to legacy single-bidder.");
      } catch (e) {
        warn("data-bidders JSON parse error (" + e.message + "); falling back to legacy single-bidder.");
      }
    }
    return [{
      bidder: "limelightDigital",
      params: {
        host: cfg.bidderHost,
        publisherId: cfg.publisherId,
        adUnitId: parseInt(cfg.adUnitId, 10),
        adUnitType: "video"
      }
    }];
  }
  cfg.bidders = resolveBidders();

  var DEBUG = /[?&]debug=true/i.test((window.location && window.location.search) || "");
  
  function step(n, m) { if (!DEBUG) return; try { console.log("%c STEP " + n + " %c " + m, "background:linear-gradient(90deg,#a370f7,#7c4dff);color:#fff;font-weight:bold;padding:2px 8px;border-radius:3px;", "color:#4ade80;"); } catch (_) {} }
  function winLog(b, c) { if (!DEBUG) return; try { console.log("%c 🏆 WINNER %c " + b + " | Raw CPM: $" + c.toFixed(2), "background:linear-gradient(90deg,#f1c40f,#e67e22);color:#000;font-weight:bold;padding:2px 8px;border-radius:3px;", "color:#f1c40f;font-weight:bold;"); } catch (_) {} }
  function noBidLog() { if (!DEBUG) return; try { console.log("%c ⚠️ NO MARKET DEMAND %c Fallback to $0.00 targeting.", "background:#3a3a3a;color:#bdc3c7;font-weight:bold;padding:2px 8px;border-radius:3px;", "color:#bdc3c7;"); } catch (_) {} }
  function warn(m) { if (!DEBUG) return; try { console.warn("[AdTechPlayer]", m); } catch (_) {} }

  // ─── Telemetry ──────────────────────────────────────────────────
  // Fire-and-forget beacons to the control-plane collector. Never throws into
  // the auction/render path; no-op unless the tag carries data-beacon-url +
  // data-account + data-placement-id. sendBeacon first (text/plain → no CORS
  // preflight), fetch keepalive fallback. Honours data-sample-rate.
  var ENGINE_VERSION = "2.6.0";
  var TELE_ON = !!(cfg.beaconUrl && cfg.account && cfg.placementId);
  var SESSION_ID = (function () {
    try { return Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10); }
    catch (_) { return "sess"; }
  })();
  function uuid() {
    try { if (window.crypto && crypto.randomUUID) return crypto.randomUUID(); } catch (_) {}
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0, v = c === "x" ? r : (r & 0x3) | 0x8; return v.toString(16);
    });
  }
  function teleConsent() {
    // Reuse whatever consent Prebid already resolved rather than re-querying a CMP.
    try {
      if (typeof pbjs !== "undefined" && pbjs.getConsentMetadata) {
        var m = pbjs.getConsentMetadata() || {};
        var g = m.gdpr || {};
        return { gdpr: !!g.gdprApplies, tcString: g.consentString || null,
                 usp: (m.usp && m.usp.uspString) || null };
      }
    } catch (_) {}
    return null;
  }
  function gamIu() {
    try { return new URL(cfg.adTagUrl).searchParams.get("iu") || null; } catch (_) { return null; }
  }
  function beacon(event, props) {
    try {
      if (!TELE_ON) return;
      if (cfg.sampleRate < 1 && Math.random() > cfg.sampleRate) return;
      var body = JSON.stringify({
        v: 1, event: event, ts: Date.now(), eventId: uuid(),
        account: cfg.account, placementId: cfg.placementId, adUnitPath: gamIu(),
        pageUrl: (window.location && window.location.href) || "", sessionId: SESSION_ID,
        engineVersion: ENGINE_VERSION, consent: teleConsent(), props: props || {}
      });
      var sent = false;
      try {
        if (navigator.sendBeacon) {
          sent = navigator.sendBeacon(cfg.beaconUrl, new Blob([body], { type: "text/plain" }));
        }
      } catch (_) {}
      if (!sent && typeof fetch === "function") {
        fetch(cfg.beaconUrl, { method: "POST", body: body, keepalive: true,
          credentials: "omit", headers: { "Content-Type": "text/plain" } }).catch(function () {});
      }
    } catch (_) {}
  }
  function imaAdInfo(e) {
    try {
      var ad = e && e.getAd && e.getAd();
      if (!ad) return {};
      return {
        adId: ad.getAdId ? ad.getAdId() : undefined,
        creativeId: ad.getCreativeId ? ad.getCreativeId() : undefined,
        adDuration: ad.getDuration ? ad.getDuration() : undefined
      };
    } catch (_) { return {}; }
  }

  function roundGran(c) { return Math.floor(c / 0.10) * 0.10; }
  function applyBias(raw) { return parseFloat(roundGran(raw + cfg.floorBias).toFixed(2)); }
  function isOutstream() { return cfg.placement === "outstream"; }

  // Stitch full Prebid targeting key-value set into GAM cust_params.
  // `targeting` is a flat string→string map: { hb_pb, hb_bidder, hb_uuid, hb_size,
  // hb_format, hb_adid, hb_pb_<bidder>, hb_uuid_<bidder>, ... }
  // hb_uuid is the cache UUID — without it, GAM cannot resolve the winning
  // bidder's cached VAST creative and no ad will play.
  function stitchTag(base, targeting) {
    try {
      var u = new URL(base);
      u.searchParams.set("correlator", Date.now().toString());
      var hb = Object.keys(targeting || {}).map(function (k) {
        return encodeURIComponent(k) + "=" + encodeURIComponent(targeting[k]);
      }).join("&");
      var existing = u.searchParams.get("cust_params") || "";
      u.searchParams.set("cust_params", existing ? existing + "&" + hb : hb);
      return u.toString();
    } catch (e) { warn("stitch: " + e.message); return base; }
  }
  function noBidTargeting() { return { hb_pb: "0.00", hb_bidder: "none" }; }

  function loadCss(href) {
    if (!href || document.querySelector('link[data-atp="' + href + '"]')) return;
    var l = document.createElement("link");
    l.rel = "stylesheet"; l.href = href; l.setAttribute("data-atp", href);
    (document.head || document.documentElement).appendChild(l);
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      if (!src) { resolve(); return; }
      var existing = document.querySelector('script[data-atp="' + src + '"]');
      if (existing) {
        if (existing.getAttribute("data-loaded") === "1") resolve();
        else existing.addEventListener("load", function () { resolve(); });
        return;
      }
      var s = document.createElement("script");
      s.src = src; s.async = false; s.setAttribute("data-atp", src);
      s.onload  = function () { s.setAttribute("data-loaded", "1"); resolve(); };
      s.onerror = function () { reject(new Error("Failed to load: " + src)); };
      (document.head || document.documentElement).appendChild(s);
    });
  }

  function ensureMount() {
    var container = document.getElementById(cfg.divId);
    if (container) return container;
    container = document.createElement("div");
    container.id = cfg.divId;
    
    // Outstream slots reserve no space until an ad actually renders — they
    // start collapsed (height:0) and expand to 16:9 only when the ad begins,
    // then collapse again on completion/error (see setupOutstream).
    var containerStyle;
    if (isOutstream()) {
      containerStyle = "max-width:960px;width:100%;margin:0 auto;position:relative;background:#000;height:0;overflow:hidden;";
    } else {
      containerStyle = cfg.fluid
        ? "max-width:960px;width:100%;margin:0 auto;position:relative;background:#000;aspect-ratio:16/9;"
        : "width:640px;height:480px;margin:0 auto;position:relative;background:#000;";
    }
    container.style.cssText = containerStyle;

    var video = document.createElement("video");
    video.id = cfg.divId + "_video";
    video.className = "video-js vjs-default-skin vjs-big-play-centered";
    video.setAttribute("playsinline", "");
    // Outstream is a standalone ad — no content controls. Instream keeps the
    // content player controls visible.
    if (!isOutstream()) video.setAttribute("controls", "");
    video.setAttribute("preload", cfg.preload);
    // `loop` is a CONTENT-video setting (instream only). Never set it for
    // outstream: there is no content video, and IMA renders the ad through
    // this same element — a loop attribute makes the ad creative restart and,
    // combined with the ALL_ADS_COMPLETED collapse, flicker the slot.
    if (cfg.loop && !isOutstream()) video.setAttribute("loop", "");
    // Outstream starts on scroll (no user gesture), so the ad must be muted for
    // the browser to allow autoplay. Mute the element up front; the ads manager
    // volume is also set to 0 at start time (see setupOutstream).
    if (isOutstream() && cfg.muted) { video.muted = true; video.setAttribute("muted", ""); }
    video.style.cssText = "width:100%;height:100%;";
    container.appendChild(video);

    if (currentScript && currentScript.parentNode) {
      currentScript.parentNode.insertBefore(container, currentScript.nextSibling);
    } else {
      (document.body || document.documentElement).appendChild(container);
    }
    step("0.5", "Mount point #" + cfg.divId + " auto-created at script position.");
    return container;
  }

  function ready(fn) {
    if (document.readyState === "complete" || document.readyState === "interactive") setTimeout(fn, 0);
    else document.addEventListener("DOMContentLoaded", fn);
  }

  function setupPlayer(finalTagUrl) {
    if (typeof videojs === "undefined") {
      warn("Video.js dependency missing.");
      return;
    }
    var container = document.getElementById(cfg.divId);
    var videoEl   = document.getElementById(cfg.divId + "_video");
    if (!container || !videoEl) return;

    var isHLS = /\.m3u8/i.test(cfg.videoUrl);
    var player;
    try {
      if (videojs.getPlayer(videoEl.id)) {
        player = videojs.getPlayer(videoEl.id);
        player.src({ src: cfg.videoUrl, type: isHLS ? "application/x-mpegURL" : "video/mp4" });
        if (cfg.autoplay) player.autoplay(cfg.autoplay);
        player.muted(cfg.muted);
        player.loop(cfg.loop);
      } else {
        player = videojs(videoEl, { autoplay: cfg.autoplay, muted: cfg.muted, controls: true, fluid: cfg.fluid, loop: cfg.loop, preload: cfg.preload, sources: [{ src: cfg.videoUrl, type: isHLS ? "application/x-mpegURL" : "video/mp4" }] });
      }
    } catch (e) { warn("player init: " + e.message); return; }

    if (typeof google === "undefined" || !google.ima) {
      warn("Google IMA SDK blocked or not loaded. Playing content directly.");
      try {
        if (cfg.autoplay) {
          player.play().catch(function(){});
        }
      } catch (_) {}
      return;
    }

    try {
      var vpMap = { insecure: google.ima.ImaSdkSettings.VpaidMode.INSECURE, enabled: google.ima.ImaSdkSettings.VpaidMode.ENABLED, disabled: google.ima.ImaSdkSettings.VpaidMode.DISABLED };
      if (vpMap[cfg.vpaidMode] !== undefined && google.ima.settings && google.ima.settings.setVpaidMode) {
        google.ima.settings.setVpaidMode(vpMap[cfg.vpaidMode]);
      }
    } catch (e) { warn("vpaid: " + e.message); }

    player.ready(function () {
      var adContainer = document.createElement("div");
      adContainer.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;z-index:-1;pointer-events:none;";
      container.style.position = container.style.position || "relative";
      container.appendChild(adContainer);
      
      try {
        var adc = new google.ima.AdDisplayContainer(adContainer, videoEl);
        var loader = new google.ima.AdsLoader(adc);
        loader.addEventListener(google.ima.AdErrorEvent.Type.AD_ERROR, function (e) {
          adContainer.style.zIndex = "-1";
          adContainer.style.pointerEvents = "none";
          beacon("ad_error", { phase: "ima_loader", errorCode: String((e && e.getError && e.getError()) || "") });
          try { player.play(); } catch (_) {}
        }, false);
        loader.addEventListener(google.ima.AdsManagerLoadedEvent.Type.ADS_MANAGER_LOADED, function (e) {
          var mgr = e.getAdsManager(videoEl);
          // Expose the manager so the sticky/floating logic can call mgr.resize()
          // and reflow the live ad creative when the player docks/undocks.
          container.__atpMgr = mgr;
          mgr.addEventListener(google.ima.AdErrorEvent.Type.AD_ERROR, function (e) {
            adContainer.style.zIndex = "-1";
            adContainer.style.pointerEvents = "none";
            container.__atpMgr = null;
            try { mgr.destroy(); } catch (_) {}
            beacon("ad_error", { phase: "ima", errorCode: String((e && e.getError && e.getError()) || "") });
            player.play().catch(function(){});
          });
          mgr.addEventListener(google.ima.AdEvent.Type.STARTED, function (ev) {
            beacon("impression", imaAdInfo(ev));
          });
          mgr.addEventListener(google.ima.AdEvent.Type.CONTENT_PAUSE_REQUESTED, function () {
            adContainer.style.zIndex = "10";
            adContainer.style.pointerEvents = "auto";
            player.pause();
          });
          mgr.addEventListener(google.ima.AdEvent.Type.CONTENT_RESUME_REQUESTED, function () {
            adContainer.style.zIndex = "-1";
            adContainer.style.pointerEvents = "none";
            player.play().catch(function(){});
          });
          mgr.addEventListener(google.ima.AdEvent.Type.COMPLETE, function () {
            beacon("ad_complete", { viewedPct: 100 });
          });
          mgr.addEventListener(google.ima.AdEvent.Type.ALL_ADS_COMPLETED, function () {
            adContainer.style.zIndex = "-1";
            adContainer.style.pointerEvents = "none";
            container.__atpMgr = null;
            try { mgr.destroy(); } catch (_) {}
          });
          var w = container.offsetWidth || 640, h = container.offsetHeight || 360;
          mgr.init(w, h, google.ima.ViewMode.NORMAL); mgr.start();
        }, false);

        var req = new google.ima.AdsRequest();
        req.adTagUrl = finalTagUrl;
        req.linearAdSlotWidth = container.offsetWidth || 640;
        req.linearAdSlotHeight = container.offsetHeight || 360;
        adc.initialize();
        loader.requestAds(req);
        step(6, "Dispatching VAST Request via Cloud Engine layer.");
      } catch (e) { warn("IMA setup: " + e.message); }
    });
  }

  // Outstream renderer. No content video — IMA renders the ad directly into
  // the (collapsed) mount. The ad is started only once the slot scrolls into
  // view, and the slot collapses again the moment the ad finishes or errors.
  function setupOutstream(finalTagUrl) {
    var container = document.getElementById(cfg.divId);
    var videoEl   = document.getElementById(cfg.divId + "_video");
    if (!container || !videoEl) return;

    function collapse() {
      container.style.height = "0";
      container.style.overflow = "hidden";
    }
    function expand() {
      container.style.height = "";
      container.style.overflow = "";
      container.style.aspectRatio = "16/9";
    }

    if (typeof google === "undefined" || !google.ima) {
      warn("Google IMA SDK blocked or not loaded. Outstream slot stays collapsed.");
      collapse();
      return;
    }

    try {
      var vpMap = { insecure: google.ima.ImaSdkSettings.VpaidMode.INSECURE, enabled: google.ima.ImaSdkSettings.VpaidMode.ENABLED, disabled: google.ima.ImaSdkSettings.VpaidMode.DISABLED };
      if (vpMap[cfg.vpaidMode] !== undefined && google.ima.settings && google.ima.settings.setVpaidMode) {
        google.ima.settings.setVpaidMode(vpMap[cfg.vpaidMode]);
      }
    } catch (e) { warn("vpaid: " + e.message); }

    var adContainer = document.createElement("div");
    adContainer.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;";
    container.appendChild(adContainer);

    try {
      var adc = new google.ima.AdDisplayContainer(adContainer, videoEl);
      var loader = new google.ima.AdsLoader(adc);

      loader.addEventListener(google.ima.AdErrorEvent.Type.AD_ERROR, function (e) {
        warn("outstream loader error: " + ((e && e.getError && e.getError()) || "unknown"));
        beacon("ad_error", { phase: "ima_loader", errorCode: String((e && e.getError && e.getError()) || "") });
        collapse();
      }, false);

      loader.addEventListener(google.ima.AdsManagerLoadedEvent.Type.ADS_MANAGER_LOADED, function (e) {
        var mgr = e.getAdsManager(videoEl);

        // Outstream autoplays muted (browser policy), so give viewers a clear
        // tap-for-sound control — the one control outstream units are expected
        // to surface. IMA does not provide a generic mute toggle, so we overlay
        // our own. It sits above the IMA ad container and toggles mgr volume.
        var ICON_MUTED = '<svg viewBox="0 0 24 24" width="18" height="18" fill="#fff" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4V5z"/><path d="M16.5 9 21 15M21 9l-4.5 6" stroke="#fff" stroke-width="2" stroke-linecap="round" fill="none"/></svg>';
        var ICON_SOUND = '<svg viewBox="0 0 24 24" width="18" height="18" fill="#fff" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18 6a8 8 0 0 1 0 12" stroke="#fff" stroke-width="2" stroke-linecap="round" fill="none"/></svg>';
        var adMuted = !!cfg.muted;
        var soundBtn = document.createElement("button");
        soundBtn.setAttribute("aria-label", "Unmute ad");
        soundBtn.innerHTML = ICON_MUTED;
        soundBtn.style.cssText = "position:absolute;bottom:10px;left:10px;width:36px;height:36px;padding:0;border:none;border-radius:50%;background:rgba(0,0,0,.6);cursor:pointer;z-index:2147483647;display:none;align-items:center;justify-content:center;";
        soundBtn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          adMuted = !adMuted;
          try { mgr.setVolume(adMuted ? 0 : 1); } catch (_) {}
          try { videoEl.muted = adMuted; } catch (_) {}
          soundBtn.innerHTML = adMuted ? ICON_MUTED : ICON_SOUND;
          soundBtn.setAttribute("aria-label", adMuted ? "Unmute ad" : "Mute ad");
        });
        container.appendChild(soundBtn);

        mgr.addEventListener(google.ima.AdErrorEvent.Type.AD_ERROR, function (ev) {
          warn("outstream ad error: " + ((ev && ev.getError && ev.getError()) || "unknown"));
          beacon("ad_error", { phase: "ima", errorCode: String((ev && ev.getError && ev.getError()) || "") });
          soundBtn.style.display = "none";
          collapse();
          try { mgr.destroy(); } catch (_) {}
        });
        mgr.addEventListener(google.ima.AdEvent.Type.STARTED, function (ev) {
          beacon("impression", imaAdInfo(ev));
        });
        mgr.addEventListener(google.ima.AdEvent.Type.COMPLETE, function () {
          beacon("ad_complete", { viewedPct: 100 });
        });
        // No content to pause/resume — just size the slot to the ad.
        mgr.addEventListener(google.ima.AdEvent.Type.CONTENT_PAUSE_REQUESTED, function () {
          expand();
          soundBtn.style.display = "flex";
        });
        mgr.addEventListener(google.ima.AdEvent.Type.ALL_ADS_COMPLETED, function () {
          soundBtn.style.display = "none";
          collapse();
          try { mgr.destroy(); } catch (_) {}
        });

        // Start the ad only when the slot is at least half visible. Muted
        // autoplay is allowed by browsers without a user gesture, which is
        // why outstream tags must be served muted.
        var started = false;
        function startAd() {
          if (started) return;
          started = true;
          try {
            var w = container.offsetWidth || 640, h = container.offsetHeight || Math.round((container.offsetWidth || 640) * 9 / 16);
            mgr.init(w, h, google.ima.ViewMode.NORMAL);
            // Mute the ad creative so the browser allows autoplay without a user
            // gesture. Outstream starts on scroll (no click), so an unmuted ad
            // would be blocked → AD_ERROR → the slot would flash and collapse.
            try { mgr.setVolume(cfg.muted ? 0 : 1); } catch (_) {}
            mgr.start();
          } catch (e) { warn("outstream start: " + e.message); collapse(); }
        }

        if (typeof IntersectionObserver === "function") {
          var io = new IntersectionObserver(function (entries) {
            for (var i = 0; i < entries.length; i++) {
              if (entries[i].isIntersecting && entries[i].intersectionRatio >= 0.5) {
                io.disconnect();
                startAd();
                break;
              }
            }
          }, { threshold: [0, 0.5, 1] });
          io.observe(container);
        } else {
          // No IntersectionObserver support — fall back to immediate start.
          startAd();
        }
        step(7, "Outstream ad loaded. Waiting for slot to enter viewport.");
      }, false);

      var req = new google.ima.AdsRequest();
      req.adTagUrl = finalTagUrl;
      req.linearAdSlotWidth = container.offsetWidth || 640;
      req.linearAdSlotHeight = Math.round((container.offsetWidth || 640) * 9 / 16);
      adc.initialize();
      loader.requestAds(req);
      step(6, "Dispatching outstream VAST request via Cloud Engine layer.");
    } catch (e) { warn("outstream IMA setup: " + e.message); collapse(); }
  }

  // Sticky / floating video. Wraps the instream mount so the wrapper holds the
  // original layout space, then pins the mount to a screen corner whenever the
  // wrapper scrolls out of the viewport. The video keeps playing while docked,
  // so the ad stays viewable. A close (×) button lets the user dismiss it.
  function setupSticky() {
    if (!cfg.sticky || isOutstream()) return;
    if (typeof IntersectionObserver !== "function") return;
    var container = document.getElementById(cfg.divId);
    if (!container || container.parentNode.getAttribute("data-atp-sticky") === "1") return;

    // Wrap the mount so the wrapper reserves the in-flow space when we dock.
    var wrapper = document.createElement("div");
    wrapper.setAttribute("data-atp-sticky", "1");
    container.parentNode.insertBefore(wrapper, container);
    wrapper.appendChild(container);

    var closeBtn = document.createElement("button");
    closeBtn.setAttribute("aria-label", "Close floating video");
    closeBtn.innerHTML = "&times;";
    // z-index sits above the IMA ad overlay (which uses z-index:10 while playing)
    // so the close control stays clickable over a running ad creative.
    closeBtn.style.cssText = "position:absolute;top:6px;right:6px;width:26px;height:26px;padding:0;border:none;border-radius:50%;background:rgba(0,0,0,.65);color:#fff;font-size:18px;line-height:1;cursor:pointer;z-index:2147483647;display:none;align-items:center;justify-content:center;";

    // Tell IMA to reflow the live ad creative to the current mount size, so the
    // ad shrinks with the player on dock and grows back on undock instead of
    // overflowing the smaller floating frame.
    function resizeAd() {
      var mgr = container.__atpMgr;
      if (!mgr || !window.google || !google.ima) return;
      try { mgr.resize(container.offsetWidth, container.offsetHeight, google.ima.ViewMode.NORMAL); } catch (_) {}
    }

    var stuck = false, dismissed = false, prevCss = "";
    function dock() {
      if (stuck || dismissed) return;
      var h = container.offsetHeight;
      if (!h) return;
      wrapper.style.height = h + "px";
      prevCss = container.style.cssText;
      container.style.cssText = prevCss +
        ";position:fixed;bottom:20px;right:20px;width:340px;max-width:42vw;height:auto;aspect-ratio:16/9;margin:0;z-index:2147483000;box-shadow:0 8px 30px rgba(0,0,0,.5);border-radius:8px;overflow:hidden;";
      closeBtn.style.display = "flex";
      stuck = true;
      resizeAd();
    }
    function undock() {
      if (!stuck) return;
      container.style.cssText = prevCss;
      wrapper.style.height = "";
      closeBtn.style.display = "none";
      stuck = false;
      resizeAd();
    }

    container.appendChild(closeBtn);
    closeBtn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      dismissed = true;
      undock();
      io.disconnect();
      try { var v = document.getElementById(cfg.divId + "_video"); if (v) v.pause(); } catch (_) {}
    });

    var io = new IntersectionObserver(function (entries) {
      var e = entries[0];
      if (dismissed) return;
      // Dock once the player has scrolled up and out of the viewport; undock as
      // soon as any part of its in-flow slot is visible again.
      if (!e.isIntersecting && e.boundingClientRect.top < 0) dock();
      else if (e.isIntersecting) undock();
    }, { threshold: 0 });
    io.observe(wrapper);
    step("6.5", "Sticky player armed — will float on scroll-out.");
  }

  // Dispatch the resolved ad tag to the correct renderer for this placement.
  function render(finalTagUrl) {
    if (isOutstream()) {
      setupOutstream(finalTagUrl);
    } else {
      setupPlayer(finalTagUrl);
      setupSticky();
    }
  }

  function runAuction() {
    var bidderNames = cfg.bidders.map(function (b) { return b.bidder; }).join(", ");
    step(1, "Auction Initialized via CDN. Bidders: " + bidderNames + " | Timeout: " + cfg.timeout + "ms");
    if (typeof pbjs === "undefined") {
      warn("Prebid failed network retrieval — Fallback active.");
      beacon("no_demand", { phase: "prebid_unavailable", fallbackServed: true });
      render(stitchTag(cfg.adTagUrl, noBidTargeting()));
      return;
    }
    pbjs.que.push(function () {
      try {
        var buckets = [];
        for (var i = 0; i <= 30; i++) buckets.push({ min: (i * 0.10).toFixed(2), max: ((i + 1) * 0.10).toFixed(2), increment: 0.10 });
        pbjs.setConfig({
          bidderTimeout: cfg.timeout,
          cache: { url: cfg.cacheUrl },
          priceGranularity: { buckets: buckets },
          // Emit per-bidder hb_*_<bidderCode> targeting keys for EVERY bid,
          // not just the winner. Lets AdOps build per-bidder GAM line items
          // (e.g. target hb_pb_incrementx separately) or do bidder-level
          // revenue attribution inside GAM reports. The standard winner-only
          // keys (hb_pb, hb_bidder, hb_uuid …) are still emitted in parallel,
          // so default GAM setups keep working unchanged.
          enableSendAllBids: true,
          // Consent defaults are tuned for non-EU traffic. We declare GDPR
          // as not-applicable via a static TCF config so the bundled
          // tcfControl module does not cancel the auction when no CMP is
          // detected on the page. USP is auto-detected from a CCPA CMP if
          // present. GPP is intentionally NOT activated — the GPP module
          // cancels the auction outright when no GPP CMP responds.
          //
          // EU / California / other-state-privacy publishers should override
          // by wrapping a pbjs.setConfig({consentManagement:{...}}) call AFTER
          // this script loads (use the pbjs.onEvent('auctionInit') hook or
          // call before the engine's auction fires).
          consentManagement: {
            gdpr: {
              cmpApi: "static",
              consentData: { getTCData: { tcString: "", gdprApplies: false } }
            },
            usp: { cmpApi: "iab", timeout: 100 }
          }
        });
      } catch (e) { warn("setConfig: " + e.message); }

      // Measure the actual rendered mount size at auction time so the bid
      // request represents the real inventory. Falls back to 640x360 if the
      // mount hasn't laid out yet (rare — auction runs after DOM ready).
      var mountEl = document.getElementById(cfg.divId);
      var mountRect = mountEl ? mountEl.getBoundingClientRect() : null;
      var pw = (mountRect && mountRect.width)  ? Math.round(mountRect.width)  : 640;
      var ph = (mountRect && mountRect.height) ? Math.round(mountRect.height) : 360;

      var code = "atp-" + Date.now();
      try {
        pbjs.addAdUnits([{
          code: code,
          mediaTypes: {
            video: { context: cfg.placement, playerSize: [pw, ph], mimes: ["video/mp4", "application/x-mpegURL"], protocols: [1,2,3,4,5,6], playbackmethod: [2], skip: 0 }
          },
          bids: cfg.bidders
        }]);
      } catch (e) { warn("addAdUnits: " + e.message); }

      step(1.5, "Requesting video ad payload. Bidders: " + bidderNames + ". Player size: " + pw + "x" + ph);

      // Telemetry: capture per-bidder outcomes + the request itself.
      try {
        pbjs.onEvent("bidResponse", function (bid) {
          beacon("bid_response", { bidder: bid.bidderCode || bid.bidder, cpm: bid.cpm,
            currency: bid.currency, status: "bid", latencyMs: bid.timeToRespond });
        });
        pbjs.onEvent("noBid", function (bid) {
          beacon("bid_response", { bidder: bid.bidder || bid.bidderCode, status: "no-bid" });
        });
        pbjs.onEvent("bidTimeout", function (data) {
          try { (data || []).forEach(function (b) { beacon("bid_response", { bidder: b.bidder, status: "timeout" }); }); } catch (_) {}
        });
        pbjs.onEvent("bidderError", function (o) {
          beacon("bid_response", { bidder: (o && o.bidderRequest && o.bidderRequest.bidderCode) || "", status: "error" });
        });
      } catch (_) {}
      beacon("bid_request", { bidders: cfg.bidders.map(function (b) { return b.bidder; }), timeout: cfg.timeout });

      try {
        pbjs.requestBids({
          timeout: cfg.timeout,
          bidsBackHandler: function () {
            var winner = null;
            try { winner = (pbjs.getHighestCpmBids(code) || [])[0]; } catch (e) { warn("getHighestCpmBids: " + e.message); }
            var finalUrl;
            if (winner) {
              // Floor min: reject the winning bid if it didn't meet the
              // publisher's minimum acceptable price. Falls through to the
              // house line item exactly as if no bidder responded.
              if (cfg.floorMin !== null && winner.cpm < cfg.floorMin) {
                noBidLog();
                beacon("no_demand", { phase: "floor_min", fallbackServed: true });
                finalUrl = stitchTag(cfg.adTagUrl, noBidTargeting());
              } else {
                // Floor max: cap the raw CPM before bias and bucketing so
                // a runaway high bid doesn't overshoot the highest line item.
                var rawCpm = (cfg.floorMax !== null && winner.cpm > cfg.floorMax) ? cfg.floorMax : winner.cpm;
                winLog(winner.bidder, rawCpm);
                var finalCpm = applyBias(rawCpm);
                step(3, "Math Engine processing. Target CPM calibrated to granular bucket bounds.");

                // Pull the full Prebid targeting set (hb_pb, hb_bidder, hb_uuid,
                // hb_size, hb_format, hb_adid, plus bidder-suffixed variants).
                // hb_uuid is the cache UUID — required for GAM to resolve the
                // winning bidder's cached VAST creative.
                var targeting = {};
                try { targeting = pbjs.getAdserverTargetingForAdUnitCode(code) || {}; }
                catch (e) { warn("getAdserverTargeting: " + e.message); }

                // Apply our floor bias to the price bucket (and the bidder-
                // suffixed variant if present) so GAM line items targeting
                // hb_pb still match the adjusted bucket.
                var cpmStr = finalCpm.toFixed(2);
                if (targeting.hb_pb) targeting.hb_pb = cpmStr;
                var bidderKey = "hb_pb_" + winner.bidder;
                if (targeting[bidderKey]) targeting[bidderKey] = cpmStr;

                finalUrl = stitchTag(cfg.adTagUrl, targeting);
                beacon("auction_win", {
                  bidder: winner.bidder, cpmRaw: rawCpm, cpmBiased: finalCpm,
                  hbPb: cpmStr, floorApplied: (cfg.floorMax !== null && winner.cpm > cfg.floorMax)
                });
              }
            } else {
              noBidLog();
              beacon("no_demand", { phase: "auction", fallbackServed: true });
              finalUrl = stitchTag(cfg.adTagUrl, noBidTargeting());
            }
            try { if (pbjs.removeAdUnit) pbjs.removeAdUnit(code); } catch (_) {}
            render(finalUrl);
          }
        });
      } catch (e) {
        warn("requestBids execution break: " + e.message);
        render(stitchTag(cfg.adTagUrl, noBidTargeting()));
      }
    });
  }

  // ─── Dynamic config resolution ──────────────────────────────────
  // Fetch the placement's RuntimeConfig and apply it over the attribute
  // defaults. A last-known-good copy is cached in localStorage so a control-
  // plane blip can never blank the player. resolveConfig() ALWAYS resolves
  // (never rejects); in static mode (no data-config-url) it resolves instantly.
  var CFG_CACHE_KEY = "atp_cfg_" + (cfg.placementId || "default");
  var CFG_TIMEOUT_MS = 1500;

  function cfgCacheGet() {
    try { var s = localStorage.getItem(CFG_CACHE_KEY); return s ? JSON.parse(s) : null; } catch (_) { return null; }
  }
  function cfgCacheSet(rc) {
    try { localStorage.setItem(CFG_CACHE_KEY, JSON.stringify(rc)); } catch (_) {}
  }

  function applyRuntimeConfig(rc) {
    if (!rc || typeof rc !== "object") return;
    function has(k) { return rc[k] !== undefined && rc[k] !== null; }
    if (has("placement"))  cfg.placement = String(rc.placement).toLowerCase();
    if (has("timeout"))    cfg.timeout = parseInt(rc.timeout, 10) || cfg.timeout;
    if (has("bias"))       { var b = parseFloat(rc.bias); if (!isNaN(b)) cfg.floorBias = b; }
    if (has("floorMin"))   cfg.floorMin = (function (v) { return isNaN(v) ? null : v; })(parseFloat(rc.floorMin));
    if (has("floorMax"))   cfg.floorMax = (function (v) { return isNaN(v) ? null : v; })(parseFloat(rc.floorMax));
    if (has("adTag"))      cfg.adTagUrl = rc.adTag || cfg.adTagUrl;
    if (has("video"))      cfg.videoUrl = rc.video || cfg.videoUrl;
    if (has("sticky"))     cfg.sticky = !!rc.sticky;
    if (has("autoplay"))   cfg.autoplay = !!rc.autoplay;
    if (has("muted"))      cfg.muted = !!rc.muted;
    if (has("fluid"))      cfg.fluid = !!rc.fluid;
    if (has("loop"))       cfg.loop = !!rc.loop;
    if (has("preload"))    cfg.preload = rc.preload || cfg.preload;
    if (has("vpaid"))      cfg.vpaidMode = rc.vpaid || cfg.vpaidMode;
    if (has("divId"))      cfg.divId = rc.divId || cfg.divId;
    if (has("cacheUrl"))   cfg.cacheUrl = rc.cacheUrl || cfg.cacheUrl;
    if (has("prebidUrl"))  cfg.prebidUrl = rc.prebidUrl || cfg.prebidUrl;
    if (has("beaconUrl"))  cfg.beaconUrl = rc.beaconUrl || cfg.beaconUrl;
    if (has("account"))    cfg.account = rc.account || cfg.account;
    if (has("sampleRate")) { var s = parseFloat(rc.sampleRate); if (!isNaN(s)) cfg.sampleRate = s; }
    if (Array.isArray(rc.bidders) && rc.bidders.length) {
      cfg.bidders = rc.bidders.map(function (b) { return { bidder: b.bidder, params: b.params || {} }; });
    }
    // Telemetry gate depends on config-supplied fields; recompute after apply.
    TELE_ON = !!(cfg.beaconUrl && cfg.account && cfg.placementId);
  }

  function resolveConfig() {
    if (!cfg.configUrl || !cfg.placementId) return Promise.resolve();  // static tag
    var url = cfg.configUrl.replace(/\/+$/, "") + "/" + encodeURIComponent(cfg.placementId);
    if (typeof fetch !== "function") { applyRuntimeConfig(cfgCacheGet()); return Promise.resolve(); }
    var ctrl = ("AbortController" in window) ? new AbortController() : null;
    var to = setTimeout(function () { if (ctrl) try { ctrl.abort(); } catch (_) {} }, CFG_TIMEOUT_MS);
    var opts = { credentials: "omit" };
    if (ctrl) opts.signal = ctrl.signal;
    return fetch(url, opts)
      .then(function (r) { return r && r.ok ? r.json() : null; })
      .then(function (rc) {
        clearTimeout(to);
        if (rc) { applyRuntimeConfig(rc); cfgCacheSet(rc); step("0.1", "Runtime config applied from control plane."); }
        else { applyRuntimeConfig(cfgCacheGet()); warn("config fetch failed (non-OK); using cached/attribute defaults."); }
      })
      .catch(function () {
        clearTimeout(to);
        applyRuntimeConfig(cfgCacheGet());
        warn("config fetch error/timeout; using cached/attribute defaults.");
      });
  }

  ready(function () {
    // Dynamic mode resolves config BEFORE mount/deps/auction so bidders, floors,
    // bias, VAST and prebidUrl reflect the backend. Static mode resolves instantly.
    resolveConfig().then(function () {
      loadCss("https://cdn.jsdelivr.net/npm/video.js@8/dist/video-js.min.css");
      ensureMount();
      beacon("player_load", {
        placement: cfg.placement,
        referrer: (document && document.referrer) || "",
        viewport: (window.innerWidth || 0) + "x" + (window.innerHeight || 0)
      });
      Promise.all([
        loadScript("https://cdn.jsdelivr.net/npm/video.js@8/dist/video.min.js"),
        loadScript("https://imasdk.googleapis.com/js/sdkloader/ima3.js"),
        loadScript(cfg.prebidUrl)
      ]).then(runAuction).catch(function (e) { warn("Dependency boot break: " + e.message); render(stitchTag(cfg.adTagUrl, noBidTargeting())); });
    });
  });
})();