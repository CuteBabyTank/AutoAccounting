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

  /* ───────── Hero backdrop: documents dissolving into ledger lines ───────── */
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
  const LEDGER_COUNT = 9;
  let ledgers = [], docs = [], particles = [];

  function resize() {
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = W * DPR; canvas.height = H * DPR;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ledgers = Array.from({ length: LEDGER_COUNT }, (_, i) => ({
      y: H * 0.22 + (i * H * 0.6) / (LEDGER_COUNT - 1),
    }));
  }

  function spawnDoc(initial = false) {
    const w = 46 + Math.random() * 26;
    docs.push({
      x: W * (0.36 + Math.random() * 0.6),
      y: initial ? H * (0.15 + Math.random() * 0.7) : H + 60,
      w, h: w * 1.3,
      rot: (Math.random() - 0.5) * 0.5,
      vr: (Math.random() - 0.5) * 0.002,
      vy: -(0.18 + Math.random() * 0.22),
      vx: 0.12 + Math.random() * 0.12,
      dissolveAt: H * (0.2 + Math.random() * 0.55),
      lines: 3 + ((Math.random() * 3) | 0),
    });
  }

  function dissolve(d) {
    for (let i = 0; i < 46; i++) {
      const lx = (Math.random() - 0.5) * d.w, ly = (Math.random() - 0.5) * d.h;
      const cos = Math.cos(d.rot), sin = Math.sin(d.rot);
      const target = ledgers[(Math.random() * ledgers.length) | 0];
      particles.push({
        x: d.x + lx * cos - ly * sin,
        y: d.y + lx * sin + ly * cos,
        vx: 0.4 + Math.random() * 1.2,
        vy: (Math.random() - 0.5) * 0.6,
        ty: target.y,
        a: 1,
        s: 1 + Math.random() * 1.6,
        green: Math.random() < 0.7,
      });
    }
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
    ctx.globalAlpha = 0.9 * fade;
    ctx.shadowColor = "rgba(15,23,42,0.10)";
    ctx.shadowBlur = 18; ctx.shadowOffsetY = 6;
    roundRect(-d.w / 2, -d.h / 2, d.w, d.h, 5);
    ctx.fillStyle = "#FFFFFF"; ctx.fill();
    ctx.shadowColor = "transparent";
    ctx.strokeStyle = "#E2E8F0"; ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = "#F1F5F9";
    ctx.beginPath();
    ctx.moveTo(d.w / 2 - 10, -d.h / 2); ctx.lineTo(d.w / 2, -d.h / 2 + 10); ctx.lineTo(d.w / 2 - 10, -d.h / 2 + 10);
    ctx.fill();
    for (let i = 0; i < d.lines; i++) {
      const lw = (d.w - 16) * (i === d.lines - 1 ? 0.45 : 0.6 + ((i * 37) % 40) / 100);
      ctx.fillStyle = i === d.lines - 1 ? "#A7F3D0" : "#E2E8F0";
      ctx.fillRect(-d.w / 2 + 8, -d.h / 2 + 12 + i * 8, lw, 3);
    }
    ctx.restore();
  }

  let t = 0, raf = 0, running = false, lastSpawn = 0;
  function frame() {
    t++;
    ctx.clearRect(0, 0, W, H);

    ledgers.forEach((l, i) => {
      const startX = W * 0.4;
      const g = ctx.createLinearGradient(startX, 0, W, 0);
      g.addColorStop(0, "rgba(5,150,105,0)");
      g.addColorStop(0.3, "rgba(5,150,105,0.38)");
      g.addColorStop(1, "rgba(5,150,105,0.12)");
      ctx.strokeStyle = g;
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 10]);
      ctx.lineDashOffset = -(t * (0.6 + i * 0.05) * SPEED);
      ctx.beginPath(); ctx.moveTo(startX, l.y); ctx.lineTo(W, l.y); ctx.stroke();
    });
    ctx.setLineDash([]);

    if (t - lastSpawn > 50 / SPEED && docs.length < 10) { spawnDoc(); lastSpawn = t; }
    for (let i = docs.length - 1; i >= 0; i--) {
      const d = docs[i];
      d.y += d.vy * SPEED; d.x += d.vx * 0.3 * SPEED; d.rot += d.vr * SPEED;
      if (!d.dissolved && d.y < d.dissolveAt + 40) { d.dissolved = true; dissolve(d); }
      if (d.y < d.dissolveAt) { docs.splice(i, 1); continue; }
      drawDoc(d);
    }

    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.vy += (p.ty - p.y) * 0.004;
      p.vy *= 0.92;
      p.vx = Math.min(p.vx * 1.012 + 0.02, 4.5);
      p.x += p.vx * SPEED; p.y += p.vy * SPEED;
      if (p.x > W * 0.8) p.a -= 0.012;
      if (p.a <= 0 || p.x > W + 10) { particles.splice(i, 1); continue; }
      ctx.globalAlpha = p.a;
      ctx.fillStyle = p.green ? "#10B981" : "#94A3B8";
      ctx.fillRect(p.x, p.y, p.s * (1 + p.vx * 0.9), p.s * 0.8);
    }
    ctx.globalAlpha = 1;

    if (running) raf = requestAnimationFrame(frame);
  }

  function start() { if (!running) { running = true; raf = requestAnimationFrame(frame); } }
  function stop() { running = false; cancelAnimationFrame(raf); }

  resize();
  for (let i = 0; i < 5; i++) spawnDoc(true);
  start();
  // Size the drawing buffer from the canvas's real box whenever it changes
  // (fonts and layout settle after first paint), so it never renders stretched.
  new ResizeObserver(() => { resize(); if (!running) frame(); }).observe(canvas);
  document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));
  new IntersectionObserver(([e]) => (e.isIntersecting ? start() : stop())).observe(canvas);

  /* ───────── Drag & drop sorting demo ───────── */
  const SAMPLES = [
    { name: "Invoice_2026.pdf", ext: "pdf", vendor: "Northwind Supply Co.", date: "Mar 14, 2026", amount: 4280.0, category: "COGS · 5000", bucket: "payable" },
    { name: "Tax_Receipt.jpg", ext: "jpg", vendor: "City Office Depot", date: "Feb 02, 2026", amount: 312.48, category: "Office · Deductible", bucket: "tax" },
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
      samplesEl.appendChild(b);
    });
  }
  renderSamples();

  // Pointer-based drag so it works with mouse, pen and touch alike. A tap processes too.
  let drag = null;
  samplesEl.addEventListener("pointerdown", (e) => {
    const el = e.target.closest(".sample");
    if (!el || el.classList.contains("used") || e.button > 0) return;
    drag = { el, x0: e.clientX, y0: e.clientY, ghost: null, moved: false };
    el.setPointerCapture(e.pointerId);
  });
  samplesEl.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (!drag.moved && Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) < 6) return;
    if (!drag.moved) {
      drag.moved = true;
      drag.ghost = drag.el.cloneNode(true);
      drag.ghost.classList.add("drag-ghost");
      drag.ghost.removeAttribute("aria-label");
      document.body.appendChild(drag.ghost);
      drag.el.classList.add("dragging");
    }
    drag.ghost.style.left = e.clientX + "px";
    drag.ghost.style.top = e.clientY + "px";
    dz.classList.toggle("over", overZone(e));
  });
  const endDrag = (e, cancelled) => {
    if (!drag) return;
    const { el, moved, ghost } = drag;
    drag = null;
    el.classList.remove("dragging");
    if (ghost) ghost.remove();
    dz.classList.remove("over");
    if (!cancelled && (!moved || overZone(e))) enqueueSample(el);
  };
  samplesEl.addEventListener("pointerup", (e) => endDrag(e, false));
  samplesEl.addEventListener("pointercancel", (e) => endDrag(e, true));
  function overZone(e) {
    const r = dz.getBoundingClientRect();
    return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
  }
  // Keyboard: Enter/Space on a focused sample arrives as a click with detail 0.
  samplesEl.addEventListener("click", (e) => {
    if (e.detail !== 0) return;
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
    [...(e.dataTransfer?.files || [])].forEach((f) => queue.push(classifyFile(f)));
    pump();
  });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());
  dz.addEventListener("click", () => { if (!busy) fileInput.click(); });
  dz.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && !busy) { e.preventDefault(); fileInput.click(); }
  });
  fileInput.addEventListener("change", () => {
    [...fileInput.files].forEach((f) => queue.push(classifyFile(f)));
    fileInput.value = "";
    pump();
  });

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
    while (queue.length) await processDoc(queue.shift());
    busy = false;
    await sleep(900);
    if (!busy) { stage.hidden = true; idle.hidden = false; }
    if (!busy && $$(".sample:not(.used)").length === 0) {
      await sleep(2500);
      if (!busy) renderSamples();
    }
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

    const t = totals[doc.bucket];
    const bEl = $(`.bucket[data-bucket="${doc.bucket}"]`);
    const from = t.sum;
    t.n += 1; t.sum += doc.amount;
    $("[data-count]", bEl).textContent = t.n;
    countUp($("[data-total]", bEl), from, t.sum, 700, money);
    bEl.classList.add("pulse");
    setTimeout(() => bEl.classList.remove("pulse"), 700);
    await sleep(300);
  }

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
