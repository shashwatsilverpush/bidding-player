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
    floorBias:   parseFloat(currentScript.getAttribute("data-bias")) || 0.10,
    videoUrl:    currentScript.getAttribute("data-video") || "",
    autoplay:    currentScript.getAttribute("data-autoplay") === "true",
    muted:       currentScript.getAttribute("data-muted") === "true",
    fluid:       currentScript.getAttribute("data-fluid") !== "false",
    loop:        currentScript.getAttribute("data-loop") === "true",
    preload:     currentScript.getAttribute("data-preload") || "metadata",
    vpaidMode:   currentScript.getAttribute("data-vpaid") || "insecure",
    divId:       currentScript.getAttribute("data-div-id") || "comparos-video-placement",
    cacheUrl:    currentScript.getAttribute("data-cache") || "https://prebid.adnxs.com/pbc/v1/cache",
    prebidUrl:   currentScript.getAttribute("data-prebid-url") || "https://cdnjs.cloudflare.com/ajax/libs/prebid.js/6.7.0/prebid.js"
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

  function roundGran(c) { return Math.floor(c / 0.10) * 0.10; }
  function applyBias(raw) { return parseFloat(roundGran(raw + cfg.floorBias).toFixed(2)); }

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
    
    var containerStyle = cfg.fluid
      ? "max-width:960px;width:100%;margin:0 auto;position:relative;background:#000;aspect-ratio:16/9;"
      : "width:640px;height:480px;margin:0 auto;position:relative;background:#000;";
    container.style.cssText = containerStyle;

    var video = document.createElement("video");
    video.id = cfg.divId + "_video";
    video.className = "video-js vjs-default-skin vjs-big-play-centered";
    video.setAttribute("playsinline", "");
    video.setAttribute("controls", "");
    video.setAttribute("preload", cfg.preload);
    if (cfg.loop) video.setAttribute("loop", "");
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
        loader.addEventListener(google.ima.AdErrorEvent.Type.AD_ERROR, function () {
          adContainer.style.zIndex = "-1";
          adContainer.style.pointerEvents = "none";
          try { player.play(); } catch (_) {}
        }, false);
        loader.addEventListener(google.ima.AdsManagerLoadedEvent.Type.ADS_MANAGER_LOADED, function (e) {
          var mgr = e.getAdsManager(videoEl);
          mgr.addEventListener(google.ima.AdErrorEvent.Type.AD_ERROR, function () {
            adContainer.style.zIndex = "-1";
            adContainer.style.pointerEvents = "none";
            try { mgr.destroy(); } catch (_) {}
            player.play().catch(function(){});
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
          mgr.addEventListener(google.ima.AdEvent.Type.ALL_ADS_COMPLETED, function () {
            adContainer.style.zIndex = "-1";
            adContainer.style.pointerEvents = "none";
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

  function runAuction() {
    var bidderNames = cfg.bidders.map(function (b) { return b.bidder; }).join(", ");
    step(1, "Auction Initialized via CDN. Bidders: " + bidderNames + " | Timeout: " + cfg.timeout + "ms");
    if (typeof pbjs === "undefined") {
      warn("Prebid failed network retrieval — Fallback active.");
      setupPlayer(stitchTag(cfg.adTagUrl, noBidTargeting()));
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
            video: { context: "instream", playerSize: [pw, ph], mimes: ["video/mp4", "application/x-mpegURL"], protocols: [1,2,3,4,5,6], playbackmethod: [2], skip: 0 }
          },
          bids: cfg.bidders
        }]);
      } catch (e) { warn("addAdUnits: " + e.message); }

      step(1.5, "Requesting video ad payload. Bidders: " + bidderNames + ". Player size: " + pw + "x" + ph);
      try {
        pbjs.requestBids({
          timeout: cfg.timeout,
          bidsBackHandler: function () {
            var winner = null;
            try { winner = (pbjs.getHighestCpmBids(code) || [])[0]; } catch (e) { warn("getHighestCpmBids: " + e.message); }
            var finalUrl;
            if (winner) {
              winLog(winner.bidder, winner.cpm);
              var finalCpm = applyBias(winner.cpm);
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
            } else {
              noBidLog();
              finalUrl = stitchTag(cfg.adTagUrl, noBidTargeting());
            }
            try { if (pbjs.removeAdUnit) pbjs.removeAdUnit(code); } catch (_) {}
            setupPlayer(finalUrl);
          }
        });
      } catch (e) {
        warn("requestBids execution break: " + e.message);
        setupPlayer(stitchTag(cfg.adTagUrl, noBidTargeting()));
      }
    });
  }

  ready(function () {
    loadCss("https://cdn.jsdelivr.net/npm/video.js@8/dist/video-js.min.css");
    ensureMount();
    Promise.all([
      loadScript("https://cdn.jsdelivr.net/npm/video.js@8/dist/video.min.js"),
      loadScript("https://imasdk.googleapis.com/js/sdkloader/ima3.js"),
      loadScript(cfg.prebidUrl)
    ]).then(runAuction).catch(function (e) { warn("Dependency boot break: " + e.message); setupPlayer(stitchTag(cfg.adTagUrl, noBidTargeting())); });
  });
})();