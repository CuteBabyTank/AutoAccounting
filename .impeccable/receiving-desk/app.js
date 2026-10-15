(() => {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const sleep = (ms) => new Promise((r) => setTimeout(r, reduceMotion ? 0 : ms));
  const usd = (n) => n.toLocaleString("en-US", { style: "currency", currency: "USD" });
  const plain = (n) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const stampDate = (d = new Date()) =>
    d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" }).replace(",", "").toUpperCase();

  // Restart a CSS animation class on an element.
  const replay = (el, cls) => { el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls); };

  /* ───────── Header rule on scroll ───────── */
  const top = $("#top");
  const onScroll = () => top.classList.toggle("scrolled", window.scrollY > 8);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ───────── The desk ───────── */
  const SAMPLES = [
    { name: "Invoice_2026.pdf", kind: "Invoice", vendor: "Northwind Supply Co.", date: "Mar 14, 2026", amount: 4280.0, category: "Inventory · COGS", acct: "2000 AP", bucket: "payable" },
    { name: "Tax_Receipt.jpg", kind: "Receipt", vendor: "City Office Depot", date: "Feb 02, 2026", amount: 312.48, category: "Office · Deductible", acct: "6410", bucket: "tax" },
    { name: "AWS_March.pdf", kind: "Invoice", vendor: "Amazon Web Services", date: "Mar 31, 2026", amount: 1894.17, category: "Software · Hosting", acct: "6810", bucket: "reconciled" },
    { name: "1099-NEC_Rivera.pdf", kind: "Tax form", vendor: "J. Rivera (contractor)", date: "Jan 28, 2026", amount: 18500.0, category: "Contract Labor", acct: "6050", bucket: "tax" },
    { name: "Chase_Mar.csv", kind: "Bank stmt", vendor: "Chase Business ••4021", date: "Mar 01, 2026", amount: 9612.55, category: "n/a · reconciliation", acct: "1010", bucket: "reconciled" },
    { name: "Uber_0309.jpg", kind: "Receipt", vendor: "Uber Technologies", date: "Mar 09, 2026", amount: 46.2, category: "Travel · Deductible", acct: "6520", bucket: "tax" },
  ];
  const TILTS = [-2.2, 1.4, -0.8, 2, -1.6, 0.9];

  const stack = $("#stack");
  const tray = $("#tray");
  const fileInput = $("#fileInput");
  const work = $("#work");
  const slip = $("#slip");
  const extractRows = $$("#extract li");
  const slipRows = $$(".slip-body > div");
  const stRec = $("#stampReceived");
  const stPost = $("#stampPosted");
  $("#stampDate").textContent = stampDate();

  const totals = { payable: 0, tax: 0, reconciled: 0 };
  const queue = [];
  let busy = false;

  function dealStack() {
    stack.textContent = "";
    SAMPLES.forEach((s, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "slip-chip";
      b.dataset.i = i;
      b.style.setProperty("--tilt", TILTS[i] + "deg");
      b.setAttribute("aria-label", `Process sample document ${s.name}`);
      const tag = document.createElement("i");
      tag.textContent = s.kind;
      b.append(tag, s.name);
      stack.appendChild(b);
    });
  }
  dealStack();

  // Pointer-driven drag: one code path for mouse, pen and touch. A tap processes too.
  let drag = null;
  const overTray = (e) => {
    const r = tray.getBoundingClientRect();
    return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
  };
  stack.addEventListener("pointerdown", (e) => {
    const el = e.target.closest(".slip-chip");
    if (!el || el.classList.contains("used") || e.button > 0) return;
    drag = { el, x0: e.clientX, y0: e.clientY, ghost: null };
    el.setPointerCapture(e.pointerId);
  });
  stack.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (!drag.ghost) {
      if (Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) < 6) return;
      drag.ghost = drag.el.cloneNode(true);
      drag.ghost.classList.add("ghost");
      drag.ghost.removeAttribute("aria-label");
      document.body.appendChild(drag.ghost);
      drag.el.classList.add("dragging");
    }
    drag.ghost.style.left = e.clientX + "px";
    drag.ghost.style.top = e.clientY + "px";
    tray.classList.toggle("over", overTray(e));
  });
  const endDrag = (e, cancelled) => {
    if (!drag) return;
    const { el, ghost } = drag;
    drag = null;
    el.classList.remove("dragging");
    if (ghost) ghost.remove();
    tray.classList.remove("over");
    if (!cancelled && (!ghost || overTray(e))) take(el);
  };
  stack.addEventListener("pointerup", (e) => endDrag(e, false));
  stack.addEventListener("pointercancel", (e) => endDrag(e, true));
  // Keyboard activation (Enter / Space) arrives as a click with detail 0.
  stack.addEventListener("click", (e) => {
    if (e.detail !== 0) return;
    const el = e.target.closest(".slip-chip");
    if (el && !el.classList.contains("used")) take(el);
  });

  function take(el) {
    el.classList.add("used");
    queue.push(SAMPLES[+el.dataset.i]);
    run();
  }

  // Real files from the visitor's computer: classified locally, never uploaded.
  ["dragenter", "dragover"].forEach((t) => tray.addEventListener(t, (e) => { e.preventDefault(); tray.classList.add("over"); }));
  ["dragleave", "dragend"].forEach((t) => tray.addEventListener(t, (e) => {
    if (!tray.contains(e.relatedTarget)) tray.classList.remove("over");
  }));
  tray.addEventListener("drop", (e) => {
    e.preventDefault();
    tray.classList.remove("over");
    [...(e.dataTransfer?.files || [])].forEach((f) => queue.push(fromFile(f)));
    run();
  });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());
  tray.addEventListener("click", () => { if (!busy) fileInput.click(); });
  tray.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && !busy) { e.preventDefault(); fileInput.click(); }
  });
  fileInput.addEventListener("change", () => {
    [...fileInput.files].forEach((f) => queue.push(fromFile(f)));
    fileInput.value = "";
    run();
  });

  function hash(str) {
    let h = 2166136261;
    for (const c of str) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
    return h >>> 0;
  }
  function fromFile(f) {
    const lower = f.name.toLowerCase();
    const ext = lower.includes(".") ? lower.split(".").pop() : "";
    let bucket = "reconciled", kind = "Document", category = "General expense", acct = "6000";
    if (/invoice|bill|inv[_\-\s]|statement of account/.test(lower)) { bucket = "payable"; kind = "Invoice"; category = "Accounts payable"; acct = "2000 AP"; }
    else if (/1099|w-?2|w-?9|1040|tax|donation/.test(lower)) { bucket = "tax"; kind = "Tax form"; category = "Tax deductible"; acct = "6050"; }
    else if (/receipt|rcpt/.test(lower) || /^(jpe?g|png|heic|webp)$/.test(ext)) { bucket = "tax"; kind = "Receipt"; category = "Expense · Deductible"; acct = "6400"; }
    else if (/statement|bank/.test(lower) || ext === "csv") { bucket = "reconciled"; kind = "Bank stmt"; category = "n/a · reconciliation"; acct = "1010"; }
    const vendor = f.name.replace(/\.[^.]+$/, "").replace(/[_\-]+/g, " ").trim().slice(0, 28) || "Unknown sender";
    const h = hash(f.name + f.size);
    return {
      name: f.name, kind, vendor, bucket, category, acct,
      date: new Date(f.lastModified || Date.now()).toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" }),
      amount: Math.round(2000 + (h % 480000)) / 100,
      illustrative: true,
    };
  }

  async function run() {
    if (busy) return;
    busy = true;
    tray.setAttribute("aria-busy", "true");
    while (queue.length) await processOne(queue.shift());
    busy = false;
    tray.removeAttribute("aria-busy");
    await sleep(700);
    if (busy) return;
    if ($$(".slip-chip:not(.used)").length === 0) { await sleep(1800); if (!busy) dealStack(); }
  }

  const valuesOf = (doc) => ({ vendor: doc.vendor, date: doc.date, amount: usd(doc.amount), category: doc.category });

  function loadSlip(doc) {
    slip.className = "slip";
    [stRec, stPost].forEach((s) => s.classList.remove("press"));
    $("#slipName").textContent = doc.name;
    $("#slipKind").textContent = doc.kind;
    $("#stampAcct").textContent = doc.acct;
    const vals = valuesOf(doc);
    slipRows.forEach((r) => { r.classList.remove("lit"); $("dd", r).textContent = vals[r.dataset.k]; });
    extractRows.forEach((r) => { r.classList.remove("hit"); $("b", r).textContent = ""; });
  }

  // Resting state: the last posted document stays on the desk, both stamps on it.
  function rest(doc) {
    loadSlip(doc);
    const vals = valuesOf(doc);
    extractRows.forEach((r) => { $("b", r).textContent = vals[r.dataset.k]; r.classList.add("hit", "still"); });
    slip.classList.add("rest");
  }

  function post(doc, animate) {
    const hole = $(`.hole[data-bucket="${doc.bucket}"]`);
    const tape = $("[data-tape]", hole);
    const li = document.createElement("li");
    li.textContent = plain(doc.amount);
    if (!animate) li.style.animation = "none";
    tape.appendChild(li);
    while (tape.children.length > 4) tape.firstElementChild.remove();
    const from = totals[doc.bucket];
    totals[doc.bucket] += doc.amount;
    if (animate) tick($("[data-total]", hole), from, totals[doc.bucket], 650);
    else $("[data-total]", hole).textContent = plain(totals[doc.bucket]);
    return hole;
  }

  // Illustrative entries already on the tapes, so the desk reads as a working desk at rest.
  [
    { bucket: "payable", amount: 1200.0 }, { bucket: "payable", amount: 642.5 },
    { bucket: "tax", amount: 87.19 }, { bucket: "tax", amount: 24.75 },
    { bucket: "reconciled", amount: 389.0 },
  ].forEach((d) => post(d, false));
  rest({ name: "Staples_0412.jpg", kind: "Receipt", vendor: "Staples #0412", date: "Mar 03, 2026", amount: 87.19, category: "Office · Deductible", acct: "6410" });

  async function processOne(doc) {
    loadSlip(doc);
    const vals = valuesOf(doc);

    replay(slip, "in");
    await sleep(500);

    // RECEIVED: the date stamp lands first.
    stRec.classList.add("press");
    replay(slip, "thud");
    await sleep(420);

    // READ: the read head passes over the slip; each field is lit as it is read.
    slip.classList.add("reading");
    const order = ["vendor", "date", "category", "amount"];
    for (const k of order) {
      await sleep(360);
      slipRows.forEach((r) => r.classList.toggle("lit", r.dataset.k === k));
      const out = extractRows.find((r) => r.dataset.k === k);
      $("b", out).textContent = vals[k];
      out.classList.add("hit");
    }
    await sleep(380);
    slipRows.forEach((r) => r.classList.remove("lit"));

    // POSTED: the one emerald moment, then the slip is filed.
    stPost.classList.add("press");
    replay(slip, "thud");
    await sleep(650);
    slip.classList.add("filed");
    await sleep(420);

    const hole = post(doc, true);
    hole.classList.add("got");
    setTimeout(() => hole.classList.remove("got"), 1100);
    await sleep(250);
    rest(doc);
    replay(slip, "in");
  }

  function tick(el, from, to, ms) {
    if (reduceMotion) { el.textContent = plain(to); return; }
    const t0 = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - t0) / ms);
      el.textContent = plain(from + (to - from) * (1 - Math.pow(1 - k, 4)));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  /* ───────── Journal: simulated intake across clients ───────── */
  const FEED = [
    ["Harbor Dental Group", "Henry Schein inv 88412.pdf", "Invoice", "2000 AP · Supplies", 2318.4],
    ["Maple & Rye Bakery", "IMG_4471.jpg", "Receipt", "5100 COGS · Flour", 412.75],
    ["Okafor Architecture", "1099-NEC D. Lee.pdf", "Tax form", "6050 Contract Labor", 14200.0],
    ["Harbor Dental Group", "Mercury_Mar.csv", "Bank stmt", "1010 Operating", 22404.0],
    ["Lumen Yoga Studio", "Mindbody_Apr.pdf", "Invoice", "6810 Software", 189.0],
    ["Maple & Rye Bakery", "Chase_Mar_export.csv", "Bank stmt", "1010 Operating", 9612.55],
    ["Okafor Architecture", "Delta_LAX_SFO.pdf", "Receipt", "6520 Travel", 642.0],
    ["Lumen Yoga Studio", "W-9 BrightStudio.pdf", "Tax form", "Vendor TIN on file", 0],
    ["Harbor Dental Group", "Staples_0412.jpg", "Receipt", "6410 Office", 87.19],
    ["Okafor Architecture", "Autodesk_renewal.pdf", "Invoice", "6810 Software", 2030.0],
    ["Maple & Rye Bakery", "Amex_Mar.csv", "Bank stmt", "2100 Card · 1 dupe", 7118.92],
    ["Lumen Yoga Studio", "Form 941 Q1.pdf", "Tax form", "2300 Payroll tax", 9204.12],
  ];
  const jbody = $("#jbody");
  let filter = "all";
  let fi = 0;
  let clock = new Date(); clock.setHours(9, 2, 0, 0);

  function stampEl(kind) {
    const s = document.createElement("span");
    s.className = "stamp " + (kind === "posted" ? "stamp--posted" : kind === "review" ? "stamp--review" : "stamp--received");
    const b = document.createElement("b");
    b.textContent = kind === "posted" ? "Posted" : kind === "review" ? "Review" : "Received";
    s.appendChild(b);
    return s;
  }

  function addRow(animate) {
    const [client, doc, kind, acct, amt] = FEED[fi % FEED.length];
    fi++;
    clock = new Date(clock.getTime() + (2 + (fi * 7) % 9) * 60000);
    const row = document.createElement("div");
    row.className = "jrow";
    row.setAttribute("role", "row");
    row.dataset.kind = kind;
    const cells = [
      ["t", clock.toTimeString().slice(0, 5)],
      ["client", client],
      ["doc", doc],
      ["kind", kind],
      ["acct", acct],
      ["num", amt ? plain(amt) : "—"],
    ];
    cells.forEach(([cls, text]) => {
      const c = document.createElement("span");
      c.setAttribute("role", "cell");
      c.className = cls;
      c.textContent = text;
      row.appendChild(c);
    });
    const st = document.createElement("span");
    st.setAttribute("role", "cell");
    st.className = "st";
    const flagged = /dupe/.test(acct);
    st.appendChild(stampEl(animate ? "received" : flagged ? "review" : "posted"));
    row.appendChild(st);
    if (filter !== "all" && kind !== filter) row.classList.add("hidden");
    jbody.prepend(row);
    while (jbody.children.length > 9) jbody.lastElementChild.remove();

    if (animate) {
      row.classList.add("fresh");
      $(".stamp", st).classList.add("press");
      setTimeout(() => {
        st.textContent = "";
        const s = stampEl(flagged ? "review" : "posted");
        s.classList.add("press");
        st.appendChild(s);
      }, reduceMotion ? 0 : 1600);
    }
  }
  for (let i = 0; i < 7; i++) addRow(false);

  let feedTimer = null;
  new IntersectionObserver(([e]) => {
    if (e.isIntersecting && !feedTimer && !reduceMotion) feedTimer = setInterval(() => addRow(true), 2400);
    else if (!e.isIntersecting && feedTimer) { clearInterval(feedTimer); feedTimer = null; }
  }).observe(jbody);

  $$(".filters button").forEach((btn) => {
    btn.addEventListener("click", () => {
      filter = btn.dataset.f;
      $$(".filters button").forEach((b) => b.setAttribute("aria-selected", String(b === btn)));
      $$(".jrow", jbody).forEach((r) => r.classList.toggle("hidden", filter !== "all" && r.dataset.kind !== filter));
    });
  });

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
  trace.appendChild(wire);
  wire.style.display = "none";

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
    const x1 = a.right - box.left + 4, y1 = a.top + a.height / 2 - box.top;
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
  $(".entry", trace).addEventListener("pointerleave", () => link(null));
  window.addEventListener("resize", () => { const on = $(".entry dl > div.on", trace); if (on) link(on); });
  // Show the idea before anyone interacts.
  new IntersectionObserver(([e], obs) => {
    if (!e.isIntersecting) return;
    obs.disconnect();
    link($('.entry dl > div[data-field="amount"]', trace));
  }, { threshold: 0.5 }).observe(trace);
})();
