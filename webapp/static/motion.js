/* webapp/static/motion.js
 * Small spring motion for the operations GUI (no dependencies, offline).
 *
 * Two pieces, each only where the page marks it:
 *   - Stat count: [data-count] numbers on the Dashboard count up from 0 once.
 *   - File drop:  [data-yaml-drop] on the rule editor reads a .yaml file into
 *                 the textarea in the browser. Nothing is sent until "保存".
 *
 * Spring values follow designbookmark "Stat card" / "File drop" (stiffness,
 * damping). The code is our own: mass 1, semi-implicit Euler, 4 substeps per
 * frame, dt capped at 1/30 s. Reduced motion: values jump to their targets.
 */
(function () {
  "use strict";

  var SPRINGS = {
    statCount: [160, 22], // Stat card: total / delta count
    zoneScale: [380, 16], // File drop: zone squash on press / drop
    zoneHover: [300, 26], // drag-over fill and lift
    coreScale: [420, 14], // circle gulp (1.2) and done dip (0.84)
    upIcon: [420, 30],    // upload arrow fades out
    flood: [260, 21],     // green fill on done
    check: [200, 26],     // check stroke draws in
    textRoll: [360, 30]   // title / subtitle roll
  };
  var STAT_STAGGER_MS = 60; // matches .stat-tile animation-delay steps in style.css
  var DROP_RESET_MS = 2600;
  var DROP_GULP_MS = 320; // a local read is instant; let the gulp land before the check
  var DROP_HOVER_LINGER_MS = 200;
  var YAML_MAX_BYTES = 256 * 1024;

  var mq = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  function reduced() { return !!(mq && mq.matches); }

  // --- spring core -------------------------------------------------------
  function Spring(name, x) {
    var p = SPRINGS[name];
    this.k = p[0]; this.c = p[1];
    this.x = x; this.v = 0; this.target = x;
  }
  Spring.prototype.to = function (t) {
    this.target = t;
    if (reduced()) { this.x = t; this.v = 0; }
    wake();
  };
  Spring.prototype.set = function (x) { this.x = x; this.v = 0; wake(); };
  Spring.prototype.kick = function (x) {
    if (reduced()) return;
    this.x = x; wake();
  };
  Spring.prototype.step = function (dt) {
    var a = -this.k * (this.x - this.target) - this.c * this.v;
    this.v += a * dt;
    this.x += this.v * dt;
  };
  Spring.prototype.atRest = function () {
    return Math.abs(this.x - this.target) < 0.001 && Math.abs(this.v) < 0.01;
  };

  var bodies = []; // { springs: [...], render: fn, tick?: fn(dt) -> bool }
  var raf = 0, last = 0;
  function wake() { if (!raf) { last = 0; raf = requestAnimationFrame(frame); } }
  function frame(now) {
    var dt = last ? Math.min((now - last) / 1000, 1 / 30) : 1 / 60;
    last = now;
    var busy = false;
    for (var i = 0; i < bodies.length; i++) {
      var b = bodies[i];
      for (var s = 0; s < b.springs.length; s++) {
        var sp = b.springs[s];
        for (var n = 0; n < 4; n++) sp.step(dt / 4);
        if (sp.atRest()) { sp.x = sp.target; sp.v = 0; } else busy = true;
      }
      if (b.tick && b.tick(dt)) busy = true;
      b.render();
    }
    raf = busy ? requestAnimationFrame(frame) : 0;
  }

  // --- Stat count ----------------------------------------------------------
  function initStatCounts() {
    var els = document.querySelectorAll("[data-count]");
    Array.prototype.forEach.call(els, function (el, i) {
      var final = parseInt(el.getAttribute("data-count"), 10);
      if (!isFinite(final) || final <= 0 || reduced()) return; // text already shows the value
      var sp = new Spring("statCount", 0);
      el.textContent = "0";
      bodies.push({
        springs: [sp],
        render: function () { el.textContent = String(Math.max(0, Math.round(sp.x))); }
      });
      setTimeout(function () { sp.to(final); }, i * STAT_STAGGER_MS);
    });
    if (els.length) wake();
  }

  // --- File drop -----------------------------------------------------------
  function fmtSize(bytes) {
    if (bytes >= 1e6) return (bytes / 1e6).toFixed(1) + " MB";
    return Math.max(1, Math.round(bytes / 1e3)) + " KB";
  }
  function shortName(name) {
    return name.length > 20 ? name.slice(0, 10) + "…" + name.slice(-8) : name;
  }
  function clamp(x, a, b) { return Math.max(a, Math.min(b, x)); }

  function initYamlDrop(zone) {
    var target = document.getElementById(zone.getAttribute("data-yaml-drop"));
    var pick = zone.querySelector("input[type=file]");
    var core = zone.querySelector(".drop-core");
    var flood = zone.querySelector(".drop-flood");
    var up = zone.querySelector(".drop-up");
    var ok = zone.querySelector(".drop-ok");
    var tick = zone.querySelector(".drop-tick");
    var title = zone.querySelector(".drop-title");
    var sub = zone.querySelector(".drop-sub");
    var status = zone.parentNode.querySelector("[role=status]");
    if (!target || !pick || !core) return;

    var idleTitle = title.textContent, idleSub = sub.textContent;
    var ZS = new Spring("zoneScale", 1), ZH = new Spring("zoneHover", 0);
    var CS = new Spring("coreScale", 1), UP = new Spring("upIcon", 1);
    var G = new Spring("flood", 0), K = new Spring("check", 0);
    var T = new Spring("textRoll", 1);
    var phase = "idle", run = 0, hoverAt = -1, clock = 0, bob = 0;
    var tickLen = tick.getTotalLength ? tick.getTotalLength() : 24;
    tick.style.strokeDasharray = tickLen;

    function say(t, s, tone) {
      title.textContent = t; sub.textContent = s;
      zone.dataset.tone = tone || "";
      if (status) status.textContent = t + "。" + s;
      T.set(0); T.to(1);
    }
    function reset(myRun) {
      if (myRun !== run) return;
      phase = "idle";
      UP.to(1); G.to(0); K.to(0);
      say(idleTitle, idleSub);
      if (status) status.textContent = "";
    }
    function fail(msg) {
      phase = "done"; run++;
      var myRun = run;
      ZS.kick(0.965); UP.to(1); G.to(0); K.to(0);
      say("読み込めませんでした", msg, "error");
      zone.classList.remove("is-shaking"); void zone.offsetWidth; zone.classList.add("is-shaking");
      setTimeout(function () { reset(myRun); }, DROP_RESET_MS);
    }
    function load(file) {
      if (!file || phase === "reading") return;
      if (!/\.ya?ml$/i.test(file.name)) { fail(".yaml か .yml のファイルを選んでください"); return; }
      if (file.size > YAML_MAX_BYTES) { fail("256 KB までのファイルにしてください"); return; }
      phase = "reading"; run++;
      var myRun = run;
      ZS.kick(0.965); CS.kick(1.2); UP.to(0);
      say("読み込み中 " + shortName(file.name), fmtSize(file.size));
      var started = Date.now();
      var settle = function () {
        var left = reduced() ? 0 : DROP_GULP_MS - (Date.now() - started);
        return new Promise(function (r) { setTimeout(r, Math.max(0, left)); });
      };
      file.text().then(function (text) {
        return settle().then(function () { return text; });
      }).then(function (text) {
        if (myRun !== run) return;
        target.value = text.replace(/\r\n/g, "\n");
        target.dispatchEvent(new Event("input", { bubbles: true }));
        phase = "done";
        CS.kick(0.84); G.to(1); K.to(1);
        say("読み込みました", shortName(file.name) + " · " + fmtSize(file.size) + " ― 「保存」を押すまで書き込まれません", "ok");
        setTimeout(function () { reset(myRun); }, DROP_RESET_MS);
      }, function () {
        if (myRun === run) fail("ファイルを読めませんでした");
      });
    }

    zone.addEventListener("dragover", function (e) {
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
      hoverAt = clock; wake();
    });
    zone.addEventListener("drop", function (e) {
      e.preventDefault();
      hoverAt = -1;
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      load(f);
    });
    zone.addEventListener("click", function (e) {
      if (e.isTrusted && e.target !== pick) pick.click();
    });
    zone.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick.click(); }
    });
    zone.addEventListener("pointerdown", function () { ZS.kick(0.975); });
    pick.addEventListener("change", function () {
      var f = pick.files && pick.files[0];
      pick.value = "";
      load(f);
    });

    bodies.push({
      springs: [ZS, ZH, CS, UP, G, K, T],
      tick: function (dt) {
        clock += dt * 1000;
        var hovering = hoverAt >= 0 && clock - hoverAt < DROP_HOVER_LINGER_MS && phase === "idle";
        if (ZH.target !== (hovering ? 1 : 0)) ZH.to(hovering ? 1 : 0);
        if (hovering && !reduced()) bob += dt * 7;
        return hovering || ZH.x > 0.001;
      },
      render: function () {
        var h = clamp(ZH.x, 0, 1);
        zone.style.setProperty("--h", h.toFixed(3));
        zone.style.transform = "scale(" + (ZS.x * (1 + 0.025 * h)).toFixed(4) + ")";
        core.style.transform = "translateY(" + (-5 * h).toFixed(2) + "px) scale(" + CS.x.toFixed(4) + ")";
        up.style.opacity = clamp(UP.x, 0, 1).toFixed(3);
        up.style.transform = "translateY(" + (Math.sin(bob) * 3.5 * h).toFixed(2) + "px) scale(" + (0.6 + 0.4 * clamp(UP.x, 0, 1)).toFixed(3) + ")";
        flood.style.transform = "scale(" + clamp(G.x, 0, 1.1).toFixed(4) + ")";
        ok.style.opacity = clamp(K.x * 4, 0, 1).toFixed(3);
        tick.style.strokeDashoffset = (tickLen * (1 - clamp(K.x, 0, 1))).toFixed(2);
        var t = clamp(T.x, 0, 1);
        var lines = [title, sub];
        for (var i = 0; i < 2; i++) {
          lines[i].style.opacity = t.toFixed(3);
          lines[i].style.transform = "translateY(" + (16 * (1 - t)).toFixed(2) + "px)";
        }
      }
    });
  }

  function init() {
    initStatCounts();
    var zones = document.querySelectorAll("[data-yaml-drop]");
    Array.prototype.forEach.call(zones, initYamlDrop);
    if (zones.length) {
      // A file dropped beside the zone would make the browser open it and drop
      // the unsaved edits, so the page swallows stray drops.
      ["dragover", "drop"].forEach(function (type) {
        document.addEventListener(type, function (e) { e.preventDefault(); });
      });
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  window.InsightMotion = { SPRINGS: SPRINGS, Spring: Spring };
})();
