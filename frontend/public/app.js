(() => {
  "use strict";

  document.documentElement.classList.add("js");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const money = (n) => n.toLocaleString("en-US", { style: "currency", currency: "USD" });
  // Reduce motion means calmer, not frozen: demo steps run a little quicker and
  // the hero backdrop drifts at under half speed.
  const sleep = (ms) => new Promise((r) => setTimeout(r, reduceMotion ? ms * 0.6 : ms));
  const SPEED = reduceMotion ? 0.4 : 1;

  /* ───────── Nav shadow on scroll ───────── */
  const navWrap = $(".nav-wrap");
  const onScroll = () => navWrap.classList.toggle("scrolled", window.scrollY > 12);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ───────── Hero backdrop: documents drifting up and fading out ───────── */
  const heroMedia = $(".hero-media");
  const video = $("#heroVideo");
  // Prefer a real motion asset (e.g. a Higgsfield render) when one is present.
  if (video && video.dataset.src) {
    video.addEventListener("loadeddata", () => {
      heroMedia.classList.add("has-video");
      if (!reduceMotion) video.play().catch(() => {});
    }, { once: true });
    video.addEventListener("error", () => video.remove(), { once: true });
    video.src = video.dataset.src;
  }

  const canvas = $("#heroCanvas");
  const ctx = canvas.getContext("2d");
  let W = 0, H = 0, DPR = 1;
  let docs = [];

  function resize() {
    measure();
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = W * DPR; canvas.height = H * DPR;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  // Documents travel in the open space around the demo card, never behind it,
  // and drift away from it. Passing behind the headline copy they thin out so
  // the text stays easy to read. Boxes are canvas-relative, refreshed on resize.
  const demoCard = $("#demo"), heroCopy = $(".hero-copy");
  let cardBox = null, copyBox = null;
  function measure() {
    const c = canvas.getBoundingClientRect();
    const rel = (el) => { const r = el.getBoundingClientRect(); return { l: r.left - c.left, r: r.right - c.left, t: r.top - c.top, b: r.bottom - c.top }; };
    cardBox = rel(demoCard); copyBox = rel(heroCopy);
  }
  function openX(w) {
    const left = cardBox.l - 16, right = cardBox.r + 16;
    for (let k = 0; k < 10; k++) {
      const x = W * (0.03 + Math.random() * 0.95);
      if (x + w / 2 < left || x - w / 2 > right) return x;
    }
    return Math.random() < 0.5 ? Math.max(w, left - w) : Math.min(W - w / 2, right + w / 2);
  }
  function overCopy(d) {
    return d.x + d.w / 2 > copyBox.l && d.x - d.w / 2 < copyBox.r && d.y + d.h / 2 > copyBox.t && d.y - d.h / 2 < copyBox.b;
  }

  function spawnDoc(initial = false) {
    const w = 54 + Math.random() * 30;
    const x = openX(w);
    const away = x < (cardBox.l + cardBox.r) / 2 ? -1 : 1;
    docs.push({
      x,
      y: initial ? H * (0.15 + Math.random() * 0.7) : H + 60,
      w, h: w * 1.3,
      rot: (Math.random() - 0.5) * 0.5,
      vr: (Math.random() - 0.5) * 0.002,
      vy: -(0.28 + Math.random() * 0.26),
      vx: away * (0.12 + Math.random() * 0.12),
      dissolveAt: H * (0.2 + Math.random() * 0.55),
      lines: 3 + ((Math.random() * 3) | 0),
    });
  }

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function drawDoc(d) {
    const fade = d.y > d.dissolveAt + 60 ? 1 : Math.max(0, (d.y - d.dissolveAt) / 60);
    ctx.save();
    ctx.translate(d.x, d.y);
    ctx.rotate(d.rot);
    // Ease toward a lower opacity behind the copy instead of popping.
    d.dim = (d.dim ?? 1) + ((overCopy(d) ? 0.35 : 1) - (d.dim ?? 1)) * 0.08;
    ctx.globalAlpha = fade * d.dim;
    ctx.shadowColor = "rgba(15,23,42,0.16)";
    ctx.shadowBlur = 20; ctx.shadowOffsetY = 8;
    roundRect(-d.w / 2, -d.h / 2, d.w, d.h, 5);
    ctx.fillStyle = "#FFFFFF"; ctx.fill();
    ctx.shadowColor = "transparent";
    ctx.strokeStyle = "#CBD5E1"; ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = "#E2E8F0";
    ctx.beginPath();
    ctx.moveTo(d.w / 2 - 10, -d.h / 2); ctx.lineTo(d.w / 2, -d.h / 2 + 10); ctx.lineTo(d.w / 2 - 10, -d.h / 2 + 10);
    ctx.fill();
    for (let i = 0; i < d.lines; i++) {
      const lw = (d.w - 16) * (i === d.lines - 1 ? 0.45 : 0.6 + ((i * 37) % 40) / 100);
      ctx.fillStyle = i === d.lines - 1 ? "#6EE7B7" : "#CBD5E1";
      ctx.fillRect(-d.w / 2 + 8, -d.h / 2 + 13 + i * 9, lw, 3.5);
    }
    ctx.restore();
  }

  let t = 0, raf = 0, running = false, lastSpawn = 0;
  function frame() {
    t++;
    ctx.clearRect(0, 0, W, H);

    if (t - lastSpawn > 34 / SPEED && docs.length < 16) { spawnDoc(); lastSpawn = t; }
    for (let i = docs.length - 1; i >= 0; i--) {
      const d = docs[i];
      d.y += d.vy * SPEED; d.x += d.vx * 0.3 * SPEED; d.rot += d.vr * SPEED;
      if (d.y < d.dissolveAt) { docs.splice(i, 1); continue; }
      drawDoc(d);
    }

    if (running) raf = requestAnimationFrame(frame);
  }

  function start() { if (!running) { running = true; raf = requestAnimationFrame(frame); } }
  function stop() { running = false; cancelAnimationFrame(raf); }

  resize();
  for (let i = 0; i < 9; i++) spawnDoc(true);
  start();
  // Size the drawing buffer from the canvas's real box whenever it changes
  // (fonts and layout settle after first paint), so it never renders stretched.
  new ResizeObserver(() => { resize(); if (!running) frame(); }).observe(canvas);
  // Web fonts can reflow the copy without resizing the canvas.
  if (document.fonts) document.fonts.ready.then(measure);
  document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));
  new IntersectionObserver(([e]) => (e.isIntersecting ? start() : stop())).observe(canvas);

  /* ───────── Page flow: line ribbons running down the whole page ─────────
     Each ribbon is a band of hairlines around a spine that meanders as it runs
     down the document. The band's width swings through zero, so it pinches into
     twists. Shapes are defined in page coordinates and drawn on one fixed canvas
     for just the visible slice, so scrolling reveals one continuous drawing from
     the hero to the footer; time adds a slow drift. */
  (() => {
    const fc = $("#flowCanvas");
    if (!fc) return;
    const g = fc.getContext("2d");
    let fw = 0, fh = 0, fdpr = 1;
    const RIBBONS = [
      // base x (0–1), meander amplitude, spine frequency, band width, twist frequency, phase, lines, ink
      { base: 0.84, amp: 0.13, f: 0.0026, width: 0.15, tf: 0.0031, ph: 0.4, n: 40, ink: [71, 85, 105], a: 0.22 },
      { base: 0.07, amp: 0.08, f: 0.0032, width: 0.09, tf: 0.0037, ph: 2.1, n: 30, ink: [71, 85, 105], a: 0.2 },
      { base: 0.5, amp: 0.44, f: 0.0011, width: 0.11, tf: 0.0024, ph: 4.0, n: 34, ink: [5, 150, 105], a: 0.12 },
    ];
    function size() {
      fdpr = Math.min(window.devicePixelRatio || 1, 2);
      fw = fc.clientWidth; fh = fc.clientHeight;
      fc.width = fw * fdpr; fc.height = fh * fdpr;
      g.setTransform(fdpr, 0, 0, fdpr, 0, 0);
    }
    let ft = 0;
    function draw() {
      ft += SPEED;
      const T = ft * 0.004, top = window.scrollY, step = 10;
      g.clearRect(0, 0, fw, fh);
      g.lineWidth = 0.8;
      for (const r of RIBBONS) {
        for (let i = 0; i < r.n; i++) {
          const u = i / (r.n - 1) - 0.5;
          // Fainter toward one edge of the band, like light falling across it.
          g.strokeStyle = `rgba(${r.ink[0]},${r.ink[1]},${r.ink[2]},${(r.a * (0.35 + 0.65 * (u + 0.5))).toFixed(3)})`;
          g.beginPath();
          for (let sy = -step; sy <= fh + step; sy += step) {
            const y = top + sy;
            const spine = fw * (r.base
              + r.amp * Math.sin(y * r.f + r.ph + T * 0.6)
              + r.amp * 0.35 * Math.sin(y * r.f * 2.3 - T * 0.4 + r.ph));
            const band = fw * r.width * Math.sin(y * r.tf + r.ph * 1.7 + T * 0.35);
            const x = spine + u * band + fw * 0.006 * Math.sin(y * 0.004 + u * 6 + T);
            if (sy < 0) g.moveTo(x, sy); else g.lineTo(x, sy);
          }
          g.stroke();
        }
      }
    }
    let on = false, id = 0;
    const loop = () => { draw(); if (on) id = requestAnimationFrame(loop); };
    const go = () => { if (!on) { on = true; id = requestAnimationFrame(loop); } };
    const halt = () => { on = false; cancelAnimationFrame(id); };
    size();
    go();
    new ResizeObserver(() => { size(); draw(); }).observe(fc);
    document.addEventListener("visibilitychange", () => (document.hidden ? halt() : go()));
  })();

  /* ───────── Drag & drop sorting demo ───────── */
  const SAMPLES = [
    { name: "Invoice_2026.pdf", ext: "pdf", vendor: "Northwind Supply Co.", date: "Mar 14, 2026", amount: 4280.0, category: "COGS · 5000", bucket: "payable" },
    { name: "Tax_Receipt.jpg", ext: "jpg", vendor: "City Office Depot", date: "Feb 02, 2026", amount: 312.48, category: "Office · Deductible", bucket: "tax" },
    {
      // Autosort: one scanned PDF holding several documents. Like the app, it's
      // split into its separate documents and each is filed on its own.
      name: "Scanned_Bundle.pdf", ext: "pdf", pages: 6, bundle: [
        { pages: "p. 1", vendor: "Staples Business", kind: "Invoice", amount: 642.9, bucket: "payable" },
        { pages: "p. 2", vendor: "Delta Air Lines", kind: "Receipt", amount: 418.0, bucket: "tax" },
        { pages: "pp. 3–4", vendor: "Mercury Bank", kind: "Statement", amount: 22404.0, bucket: "reconciled" },
        { pages: "p. 5", vendor: "FedEx Office", kind: "Receipt", amount: 87.35, bucket: "tax" },
        { pages: "p. 6", vendor: "Sysco", kind: "Invoice", amount: 1150.6, bucket: "payable" },
      ],
    },
    { name: "AWS_March.pdf", ext: "pdf", vendor: "Amazon Web Services", date: "Mar 31, 2026", amount: 1894.17, category: "Software · 6810", bucket: "reconciled" },
    { name: "1099-NEC_Form.pdf", ext: "pdf", vendor: "J. Rivera (contractor)", date: "Jan 28, 2026", amount: 18500.0, category: "Contract Labor", bucket: "tax" },
    { name: "Chase_Statement.csv", ext: "csv", vendor: "Chase Business", date: "Mar 01, 2026", amount: 9612.55, category: "n/a · Bank match", bucket: "reconciled" },
    { name: "Uber_Receipt.jpg", ext: "jpg", vendor: "Uber Technologies", date: "Mar 09, 2026", amount: 46.2, category: "Travel · Deductible", bucket: "tax" },
  ];

  const samplesEl = $("#samples");
  const dz = $("#dropzone");
  const fileInput = $("#fileInput");
  const stage = $("#scanStage");
  const idle = $(".dz-idle");
  const fieldEls = $$(".field", stage);
  const totals = { payable: { n: 0, sum: 0 }, tax: { n: 0, sum: 0 }, reconciled: { n: 0, sum: 0 } };
  const queue = [];
  let busy = false;

  function renderSamples() {
    samplesEl.textContent = "";
    SAMPLES.forEach((s, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "sample";
      b.dataset.i = i;
      b.setAttribute("aria-label", `Process sample ${s.name}`);
      const ext = document.createElement("span");
      ext.className = `ext ${s.ext}`;
      ext.textContent = s.ext.toUpperCase();
      b.append(ext, s.name);
      if (s.bundle) {
        b.classList.add("bundle");
        const pg = document.createElement("span");
        pg.className = "pages";
        pg.textContent = `${s.pages} pages`;
        b.append(pg);
        b.setAttribute("aria-label", `Auto-sort sample ${s.name}, ${s.pages} pages`);
      }
      samplesEl.appendChild(b);
    });
  }
  renderSamples();

  // Samples are buttons: a click, tap or Enter/Space sorts one. (Real files can
  // still be dropped onto the zone from the desktop.)
  samplesEl.addEventListener("click", (e) => {
    const el = e.target.closest(".sample");
    if (el && !el.classList.contains("used")) enqueueSample(el);
  });

  function enqueueSample(el) {
    el.classList.add("used");
    queue.push(SAMPLES[+el.dataset.i]);
    pump();
  }

  // Real files from the OS: classified locally, never uploaded.
  ["dragenter", "dragover"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); })
  );
  ["dragleave", "dragend"].forEach((ev) => dz.addEventListener(ev, (e) => {
    if (!dz.contains(e.relatedTarget)) dz.classList.remove("over");
  }));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dz.classList.remove("over");
    takeFiles([...(e.dataTransfer?.files || [])]);
  });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());
  dz.addEventListener("click", () => { if (!busy) fileInput.click(); });
  dz.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && !busy) { e.preventDefault(); fileInput.click(); }
  });
  fileInput.addEventListener("change", () => {
    const files = [...fileInput.files];
    fileInput.value = "";
    takeFiles(files);
  });

  // A multi-page PDF is auto-sorted as a bundle; anything else is one document.
  async function takeFiles(files) {
    noteUser();
    for (const f of files) {
      const pages = /\.pdf$/i.test(f.name) ? await countPdfPages(f) : 1;
      queue.push(pages > 1 ? bundleFromFile(f, pages) : classifyFile(f));
    }
    pump();
  }
  // Page count read locally from the PDF's own page objects; nothing is uploaded.
  async function countPdfPages(f) {
    try {
      const text = new TextDecoder("latin1").decode(await f.slice(0, 8 * 1024 * 1024).arrayBuffer());
      const objects = (text.match(/\/Type\s*\/Page(?![a-zA-Z])/g) || []).length;
      const counts = [...text.matchAll(/\/Count\s+(\d+)/g)].map((m) => +m[1]);
      return Math.max(objects, counts.length ? Math.max(...counts) : 0, 1);
    } catch { return 1; }
  }
  function bundleFromFile(f, pages) {
    const KINDS = [["Invoice", "payable"], ["Receipt", "tax"], ["Statement", "reconciled"], ["Receipt", "tax"]];
    const base = classifyFile(f);
    const n = Math.min(pages, 6);
    const bundle = Array.from({ length: n }, (_, i) => {
      const h = hash(f.name + f.size + i);
      const [kind, bucket] = KINDS[h % KINDS.length];
      return { pages: `p. ${i + 1}`, vendor: `document ${i + 1}`, kind, bucket, amount: Math.round(2000 + (h % 380000)) / 100 };
    });
    return { name: base.name, ext: "pdf", pages, bundle };
  }

  function hash(str) {
    let h = 2166136261;
    for (const c of str) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
    return h >>> 0;
  }
  function classifyFile(f) {
    const name = f.name;
    const lower = name.toLowerCase();
    const ext = (lower.split(".").pop() || "pdf").slice(0, 4);
    const h = hash(name + f.size);
    let bucket = "reconciled", category = "General Expense · 6000";
    if (/invoice|bill|inv[_\-\s]/.test(lower)) { bucket = "payable"; category = "Accounts Payable · 2000"; }
    else if (/tax|1099|w-?2|w-?9|receipt|donation|1040/.test(lower)) { bucket = "tax"; category = "Tax Deductible"; }
    else if (/statement|bank/.test(lower) || ext === "csv") { bucket = "reconciled"; category = "n/a · Bank match"; }
    const vendor = name.replace(/\.[^.]+$/, "").replace(/[_\-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()).slice(0, 26) || "Unknown Vendor";
    const d = new Date(f.lastModified || Date.now());
    return {
      name, ext, vendor, bucket, category,
      date: d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" }),
      amount: Math.round(2000 + (h % 480000)) / 100,
    };
  }

  async function pump() {
    if (busy) return;
    busy = true;
    while (queue.length) {
      const doc = queue.shift();
      await (doc.bundle ? processBundle(doc) : processDoc(doc));
    }
    busy = false;
    lastDone = performance.now();
    await sleep(900);
    if (!busy) { stage.hidden = true; idle.hidden = false; }
    if (!busy && $$(".sample:not(.used)").length === 0) {
      await sleep(2500);
      if (!busy) { renderSamples(); resetBuckets(); }
    }
  }

  function resetBuckets() {
    Object.keys(totals).forEach((k) => {
      totals[k] = { n: 0, sum: 0 };
      const bEl = $(`.bucket[data-bucket="${k}"]`);
      $("[data-count]", bEl).textContent = "0";
      $("[data-total]", bEl).textContent = money(0);
    });
  }

  function fileInto(bucket, amount) {
    const t = totals[bucket];
    const bEl = $(`.bucket[data-bucket="${bucket}"]`);
    const from = t.sum;
    t.n += 1; t.sum += amount;
    $("[data-count]", bEl).textContent = t.n;
    countUp($("[data-total]", bEl), from, t.sum, 700, money);
    bEl.classList.add("pulse");
    setTimeout(() => bEl.classList.remove("pulse"), 700);
  }

  // Autosort: scan the whole file, list the separate documents found in it,
  // then file each into its own bucket.
  const splitEl = $("#split");
  const fieldsEl = $("#fields");
  const BUCKET_NAMES = { payable: "Accounts Payable", tax: "Tax Deductions", reconciled: "Reconciled Expenses" };
  async function processBundle(doc) {
    idle.hidden = true;
    stage.hidden = false;
    fieldsEl.hidden = true;
    splitEl.hidden = false;
    stage.classList.remove("flying", "scanning");
    $("#scanName").textContent = `${doc.name} · ${doc.pages} pages`;
    $(".split-head", splitEl).textContent = `Splitting ${doc.pages} pages…`;
    const list = $("ol", splitEl);
    list.textContent = "";
    void stage.offsetWidth;
    stage.classList.add("scanning");
    await sleep(700);

    $(".split-head", splitEl).textContent = `Found ${doc.bundle.length} documents`;
    const rows = doc.bundle.map((d) => {
      const li = document.createElement("li");
      const pg = document.createElement("span"); pg.className = "pg"; pg.textContent = d.pages;
      const nm = document.createElement("span"); nm.className = "nm"; nm.textContent = `${d.kind} · ${d.vendor}`;
      const to = document.createElement("span"); to.className = "to"; to.textContent = BUCKET_NAMES[d.bucket];
      li.append(pg, nm, to);
      list.appendChild(li);
      return li;
    });
    for (const li of rows) { await sleep(220); li.classList.add("in"); }
    await sleep(450);
    for (let i = 0; i < rows.length; i++) {
      rows[i].classList.add("sorted");
      fileInto(doc.bundle[i].bucket, doc.bundle[i].amount);
      await sleep(420);
    }
    $(".split-head", splitEl).textContent = `${doc.bundle.length} documents sorted`;
    await sleep(700);
    stage.classList.add("flying");
    await sleep(450);
    splitEl.hidden = true;
    fieldsEl.hidden = false;
  }

  async function processDoc(doc) {
    idle.hidden = true;
    stage.hidden = false;
    stage.classList.remove("flying", "scanning");
    $("#scanName").textContent = doc.name;
    fieldEls.forEach((f) => { f.classList.remove("hit"); $("b", f).textContent = ""; });
    void stage.offsetWidth; // restart CSS animations
    stage.classList.add("scanning");

    const values = { vendor: doc.vendor, date: doc.date, amount: money(doc.amount), category: doc.category };
    await sleep(350);
    for (const f of fieldEls) {
      await sleep(420);
      $("b", f).textContent = values[f.dataset.k];
      f.classList.add("hit");
    }
    await sleep(450);
    stage.classList.add("flying");
    await sleep(450);

    fileInto(doc.bucket, doc.amount);
    await sleep(300);
  }

  /* Autoplay: while the demo is on screen and nobody is using it, it presses the
     next sample itself (bundle included). Any touch, click or key hands control
     back; it picks up again after a quiet spell. */
  const demoEl = $("#demo");
  const hintEl = $(".demo-hint");
  const HINT = hintEl.textContent;
  const QUIET_MS = 9000;
  let lastUser = -Infinity, lastDone = -Infinity, demoOnScreen = false, autoBusy = false;
  function noteUser() { lastUser = performance.now(); hintEl.textContent = HINT; }
  ["pointerdown", "keydown"].forEach((ev) => demoEl.addEventListener(ev, (e) => { if (e.isTrusted) noteUser(); }));
  dz.addEventListener("dragenter", noteUser);
  new IntersectionObserver(([e]) => { demoOnScreen = e.isIntersecting; }, { threshold: 0.4 }).observe(demoEl);

  async function autoPress(el) {
    autoBusy = true;
    hintEl.textContent = "Playing by itself · tap a file to take over";
    el.classList.add("auto-press");
    await sleep(260);
    if (!reduceMotion) {
      const a = el.getBoundingClientRect(), b = dz.getBoundingClientRect();
      const ghost = el.cloneNode(true);
      ghost.classList.remove("auto-press");
      ghost.classList.add("drag-ghost");
      ghost.removeAttribute("aria-label");
      ghost.style.left = a.left + a.width / 2 + "px";
      ghost.style.top = a.top + a.height / 2 + "px";
      document.body.appendChild(ghost);
      el.classList.add("dragging");
      const dx = b.left + b.width / 2 - (a.left + a.width / 2), dy = b.top + b.height / 2 - (a.top + a.height / 2);
      dz.classList.add("over");
      await ghost.animate(
        [{ transform: "translate(-50%, -50%) rotate(-3deg)" }, { transform: `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) rotate(2deg) scale(.92)`, opacity: 0.9 }],
        { duration: 650, easing: "cubic-bezier(0.32, 0.72, 0, 1)" }
      ).finished.catch(() => {});
      ghost.remove();
      el.classList.remove("dragging");
      dz.classList.remove("over");
    }
    el.classList.remove("auto-press");
    autoBusy = false;
    if (!el.classList.contains("used")) enqueueSample(el);
  }

  setInterval(() => {
    const now = performance.now();
    if (!demoOnScreen || document.hidden || busy || autoBusy || queue.length) return;
    if (now - lastUser < QUIET_MS || now - lastDone < 1800) return;
    const next = $(".sample:not(.used)", samplesEl);
    if (next) autoPress(next);
  }, 500);

  function countUp(el, from, to, ms, fmt) {
    if (reduceMotion) { el.textContent = fmt(to); return; }
    const t0 = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - t0) / ms);
      el.textContent = fmt(from + (to - from) * (1 - Math.pow(1 - k, 3)));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  /* ───────── Live sorting grid (simulated, four clients) ─────────
     Each item: [document, "client · where it went", amount, review reason?].
     A review reason is one the app actually raises; the item stops there. */
  const peso = (n) => "₱" + n.toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const LIVE = [
    {
      title: "Sales", tag: "Output VAT", color: ["#EEF2FF", "#4F46E5"],
      items: [
        ["Sales invoice #0981", "Dela Cruz Bakery · Sales", 18450.0],
        ["Sales invoice #2207", "Tan Hardware · Sales", 64200.0],
        ["Collection receipt #0412", "Lakbay Travel · Paid SI #3310", 22000.0],
        ["Sales invoice #0982", "Dela Cruz Bakery · Sales", 9875.0, "Possible duplicate"],
        ["Service invoice #3311", "Lakbay Travel · Sales", 41500.0],
      ],
    },
    {
      title: "Purchases & expenses", tag: "Input VAT", color: ["#FFFBEB", "#B45309"],
      items: [
        ["Meralco · Aug bill", "Dela Cruz Bakery · Utilities", 12384.6],
        ["Santos Hardware SI #4127", "Dela Cruz Bakery · Repairs", 7500.0],
        ["Petron receipt", "Tan Hardware · Transportation", 3150.0],
        ["Flour supplier OR", "Dela Cruz Bakery · Raw materials", 28600.0, "Seller not VAT-registered"],
        ["PLDT · Aug bill", "Reyes Dental · Utilities", 2899.0],
        ["Grab receipt", "Reyes Dental · Transportation", 486.0, "Not addressed to client"],
      ],
    },
    {
      title: "BIR 2307s", tag: "Creditable tax", color: ["#ECFDF5", "#059669"],
      items: [
        ["2307 from Mercury Corp.", "Tan Hardware · 1% goods · Q3", 1250.0],
        ["2307 from St. Luke's", "Reyes Dental · 10% prof. fees · Q3", 8400.0],
        ["2307 from Aboitiz", "Lakbay Travel · 2% services · Q3", 3020.0],
        ["2307 from SM Supermalls", "Dela Cruz Bakery · 5% rent · Q3", 6000.0, "TIN belongs to another client"],
      ],
    },
    {
      title: "Payroll", tag: "Withholding", color: ["#F1F5F9", "#334155"],
      items: [
        ["Payroll register · Aug", "Tan Hardware · 14 employees", 286400.0],
        ["Payroll register · Aug", "Reyes Dental · 6 employees", 132750.0],
        ["SSS · PhilHealth · Pag-IBIG", "Dela Cruz Bakery · Aug", 18920.0],
        ["Payroll register · Aug", "Lakbay Travel · 9 employees", 198300.0],
      ],
    },
  ];

  const grid = $("#liveGrid");
  const liveState = LIVE.map((c, ci) => {
    const card = document.createElement("article");
    card.className = "live-card reveal";
    card.style.transitionDelay = ci * 0.08 + "s";
    const head = document.createElement("div");
    head.className = "live-head";
    const h3 = document.createElement("h3");
    h3.textContent = c.title;
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.style.background = c.color[0];
    tag.style.color = c.color[1];
    tag.textContent = c.tag;
    head.append(h3, tag);
    const meta = document.createElement("p");
    meta.className = "live-meta";
    meta.innerHTML = '<b class="tnum" data-n>0</b> sorted this morning';
    const feed = document.createElement("div");
    feed.className = "feed";
    card.append(head, meta, feed);
    grid.appendChild(card);
    return { c, card, feed, idx: ci, n: 0 };
  });

  function pushLive(s) {
    const [name, sub, amt, reason] = s.c.items[s.idx % s.c.items.length];
    s.idx++;
    const el = document.createElement("div");
    el.className = "feed-item processing";
    const cells = [["fi-name", name], ["fi-amt tnum", peso(amt)], ["fi-sub", sub], ["fi-state", "Reading…"]];
    cells.forEach(([cls, text]) => {
      const sp = document.createElement("span");
      sp.className = cls;
      sp.textContent = text;
      el.appendChild(sp);
    });
    s.feed.prepend(el);
    while (s.feed.children.length > 5) s.feed.lastElementChild.remove();
    setTimeout(() => {
      el.classList.remove("processing");
      el.classList.add(reason ? "flagged" : "done");
      $(".fi-state", el).textContent = reason ? "Needs review" : "Sorted";
      if (reason) $(".fi-sub", el).textContent = reason;
      else { s.n++; $("[data-n]", s.card).textContent = s.n.toLocaleString(); }
    }, reduceMotion ? 700 : 1300);
  }

  liveState.forEach((s) => { for (let i = 0; i < 4; i++) pushLive(s); });
  let liveTimer = null;
  new IntersectionObserver(([e]) => {
    if (e.isIntersecting && !liveTimer) {
      let k = 0;
      liveTimer = setInterval(() => { pushLive(liveState[k % liveState.length]); k++; }, reduceMotion ? 1800 : 1100);
    } else if (!e.isIntersecting && liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  }).observe(grid);

  /* ───────── Source trail: entry field → spot on the receipt ───────── */
  const trace = $("#traceDemo");
  const NS = "http://www.w3.org/2000/svg";
  const wire = document.createElementNS(NS, "svg");
  wire.setAttribute("class", "wire");
  wire.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(NS, "path");
  const dotA = document.createElementNS(NS, "circle");
  const dotB = document.createElementNS(NS, "circle");
  [dotA, dotB].forEach((d) => d.setAttribute("r", "3.5"));
  wire.append(path, dotA, dotB);
  wire.style.display = "none";
  trace.appendChild(wire);

  function link(row) {
    $$(".entry dl > div", trace).forEach((r) => r.classList.toggle("on", r === row));
    $$("[data-src]", trace).forEach((s) => s.classList.remove("lit"));
    if (!row) { wire.style.display = "none"; return; }
    const src = $(`[data-src="${row.dataset.field}"]`, trace);
    if (!src) return;
    src.classList.add("lit");
    const box = trace.getBoundingClientRect();
    const a = src.getBoundingClientRect();
    const b = row.getBoundingClientRect();
    const x1 = a.right - box.left + 6, y1 = a.top + a.height / 2 - box.top;
    const x2 = b.left - box.left, y2 = b.top + b.height / 2 - box.top;
    const mx = (x1 + x2) / 2;
    path.setAttribute("d", `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`);
    dotA.setAttribute("cx", x1); dotA.setAttribute("cy", y1);
    dotB.setAttribute("cx", x2); dotB.setAttribute("cy", y2);
    wire.style.display = "";
  }
  $$(".entry dl > div", trace).forEach((row) => {
    row.addEventListener("pointerenter", () => link(row));
    row.addEventListener("focus", () => link(row));
    row.addEventListener("click", () => link(row));
  });
  window.addEventListener("resize", () => { const on = $(".entry dl > div.on", trace); if (on) link(on); });
  new IntersectionObserver(([e], obs) => {
    if (!e.isIntersecting) return;
    obs.disconnect();
    link($('.entry dl > div[data-field="amount"]', trace));
  }, { threshold: 0.5 }).observe(trace);

  /* ───────── Scroll reveal ───────── */
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
  }, { threshold: 0.15 });
  $$(".reveal").forEach((el) => io.observe(el));

  /* ───────── Magnetic CTAs ───────── */
  if (!reduceMotion && window.matchMedia("(hover: hover)").matches) {
    $$(".magnetic").forEach((btn) => {
      btn.addEventListener("pointermove", (e) => {
        const r = btn.getBoundingClientRect();
        const x = (e.clientX - r.left - r.width / 2) * 0.18;
        const y = (e.clientY - r.top - r.height / 2) * 0.28;
        btn.style.transform = `translate(${x}px, ${y - 2}px)`;
      });
      btn.addEventListener("pointerleave", () => { btn.style.transform = ""; });
    });
  }
})();
