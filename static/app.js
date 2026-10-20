(() => {
  "use strict";

  const MAX = 20;
  const $ = (id) => document.getElementById(id);
  const el = {
    intro: $("intro"), panel: $("input-panel"), links: $("links"), paste: $("paste"), clear: $("clear"),
    slots: $("slots"), count: $("count"), notice: $("notice"), go: $("go"),
    results: $("results"), summary: $("summary"), all: $("all"), allHint: $("all-hint"),
    leftover: $("leftover"), again: $("again"), list: $("list"), expires: $("expires"),
  };
  const state = {
    phase: "input", job: null, timer: null, fails: 0, leftover: [], rows: new Map(),
    got: new Set(), // bu listede indirilen dosyaların adresleri
    busy: false,    // "Hepsini indir" sürüyor mu
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const session = {
    get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch { /* gizli sekme */ } },
    del(k) { try { sessionStorage.removeItem(k); } catch { /* gizli sekme */ } },
  };

  // --- link ayıklama (sunucudaki kuralın aynısı) -----------------------
  const IG = /^(?:https?:\/\/)?(?:www\.|m\.)?instagram\.com\/(?:[A-Za-z0-9_.]{1,30}\/)?(p|reels?|tv)\/([A-Za-z0-9_-]{5,64})(?:[\/?#].*)?$/i;
  const EDGE = /^[<>()[\]"']+|[<>()[\]"']+$/g;

  function parseLinks(text) {
    const links = [], rejected = [], seen = new Set();
    let dupes = 0;
    for (const raw of text.split(/[\s,;]+/)) {
      const tok = raw.replace(EDGE, "").replace(/[.,!?;:]+$/, "").replace(EDGE, "");
      if (!tok) continue;
      const looksUrl = /^http/i.test(tok) || (tok.includes(".") && tok.includes("/"));
      if (!looksUrl) continue;
      const m = tok.match(IG);
      if (!m) { rejected.push(tok); continue; }
      let kind = m[1].toLowerCase();
      if (kind.startsWith("reel")) kind = "reel";
      const code = m[2];
      if (seen.has(code)) { dupes++; continue; }
      seen.add(code);
      links.push({ kind, code, url: `https://www.instagram.com/${kind}/${code}/` });
    }
    return { links, rejected, dupes };
  }

  // --- 20'lik şerit ----------------------------------------------------
  const slots = [];
  for (let i = 0; i < MAX; i++) {
    const s = document.createElement("span");
    s.className = "slot";
    s.style.setProperty("--i", i);
    el.slots.appendChild(s);
    slots.push(s);
  }

  function paintInputSlots(filled) {
    slots.forEach((s, i) => {
      const was = s.classList.contains("filled");
      s.className = "slot" + (i < filled ? " filled" : "");
      s.style.removeProperty("--p");
      if (i < filled && !was) s.classList.add("pop");
    });
  }

  function paintJobSlots(items) {
    slots.forEach((s, i) => {
      const it = items[i];
      s.className = "slot" + (it ? " " + it.status : "");
      if (it && it.status === "running") s.style.setProperty("--p", it.progress);
      else s.style.removeProperty("--p");
    });
  }

  // --- giriş ekranı ----------------------------------------------------
  function setNotice(lines, isError = false) {
    const text = (Array.isArray(lines) ? lines : [lines]).filter(Boolean).join("\n");
    el.notice.textContent = text;
    el.notice.hidden = !text;
    el.notice.classList.toggle("is-error", isError && !!text);
  }

  function onInput() {
    const { links, rejected, dupes } = parseLinks(el.links.value);
    const n = links.length, used = Math.min(n, MAX);
    paintInputSlots(used);
    el.count.innerHTML = `<b>${used}</b> / ${MAX} link`;
    const notes = [];
    if (n > MAX) notes.push(`${n} link var. İlk ${MAX} tanesi indirilecek, kalan ${n - MAX} link bir sonraki tura kalacak.`);
    if (rejected.length) notes.push(`${rejected.length} link Instagram video linki değil, atlandı. Profil ve hikâye linkleri desteklenmiyor.`);
    if (dupes) notes.push(`${dupes} link tekrar ediyordu, bir kez sayıldı.`);
    setNotice(notes);
    el.go.disabled = n === 0;
    el.go.textContent = n === 0 ? "Videoları indir" : `${used} videoyu indir`;
    el.clear.hidden = !el.links.value;
  }

  async function start() {
    const { links } = parseLinks(el.links.value);
    if (!links.length) return;
    const batch = links.slice(0, MAX);
    el.go.disabled = true;
    el.go.textContent = "Başlatılıyor…";
    let res, data = {};
    try {
      res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ urls: batch.map((l) => l.url) }),
      });
      data = await res.json().catch(() => ({}));
    } catch {
      onInput();
      setNotice("Sunucuya ulaşılamadı. İnternet bağlantını kontrol edip tekrar dene.", true);
      return;
    }
    if (!res.ok) {
      onInput();
      setNotice(data.error || "Liste başlatılamadı. Tekrar dene.", true);
      return;
    }
    state.leftover = links.slice(MAX).map((l) => l.url);
    session.set("kepce.job", data.id);
    session.set("kepce.leftover", state.leftover.join("\n"));
    showResults(data);
  }

  // --- sonuç ekranı ----------------------------------------------------
  function setPhase(phase) {
    state.phase = phase;
    const input = phase === "input";
    el.intro.hidden = !input;
    el.panel.hidden = !input;
    el.count.hidden = !input;
    el.go.hidden = !input;
    if (!input) el.notice.hidden = true;
    el.results.hidden = input;
  }

  function showResults(job) {
    clearTimeout(state.timer);
    state.job = job;
    state.fails = 0;
    state.got = new Set(JSON.parse(session.get(`kepce.got.${job.id}`) || "[]"));
    state.rows.clear();
    el.list.textContent = "";
    job.items.forEach((it, i) => {
      const row = buildRow(i);
      state.rows.set(it.id, row);
      el.list.appendChild(row.li);
    });
    setPhase("results");
    render(job);
    window.scrollTo({ top: 0 });
    if (!job.finished) poll(800);
  }

  function buildRow(index) {
    const li = document.createElement("li");
    li.className = "row";
    li.innerHTML =
      `<div class="thumb"><span>${index + 1}</span></div>` +
      `<div class="row-main"><p class="row-title"></p><p class="row-status"></p><div class="bar"><i></i></div></div>` +
      `<div class="row-actions"></div>`;
    return {
      li,
      thumb: li.querySelector(".thumb"),
      title: li.querySelector(".row-title"),
      status: li.querySelector(".row-status"),
      bar: li.querySelector(".bar i"),
      actions: li.querySelector(".row-actions"),
      key: "",
      thumbUrl: "",
    };
  }

  const mb = (bytes) =>
    (bytes / 1048576).toLocaleString("tr-TR", { maximumFractionDigits: 1, minimumFractionDigits: bytes < 10485760 ? 1 : 0 }) + " MB";

  function statusText(it) {
    if (it.status === "queued") return "Sırada";
    if (it.status === "running") return `İndiriliyor %${it.progress}`;
    if (it.status === "error") return it.error || "İndirilemedi";
    const total = it.files.reduce((a, f) => a + f.size, 0);
    return it.files.length > 1 ? `${it.files.length} video hazır, ${mb(total)}` : `Hazır, ${mb(total)}`;
  }

  function renderRow(row, it) {
    row.li.className = "row " + it.status;
    row.title.textContent = it.owner ? "@" + it.owner : `${it.kind === "reel" ? "Reels" : "Gönderi"} ${it.code}`;
    row.title.title = it.url;
    row.status.textContent = statusText(it);
    row.bar.style.setProperty("--p", it.progress);

    const thumbUrl = it.status === "done" && it.files[0] ? it.files[0].thumb || "" : "";
    if (thumbUrl !== row.thumbUrl) {
      row.thumbUrl = thumbUrl;
      row.thumb.querySelector("img")?.remove();
      if (thumbUrl) {
        const img = new Image();
        img.alt = "";
        img.decoding = "async";
        img.src = thumbUrl;
        row.thumb.appendChild(img);
      }
    }

    const gotCount = it.files.filter((f) => state.got.has(f.url)).length;
    const key = `${it.status}|${it.files.length}|${it.can_retry}|${gotCount}`;
    if (key === row.key) return;
    row.key = key;
    row.actions.textContent = "";
    if (it.status === "done") {
      it.files.forEach((f, n) => {
        const got = state.got.has(f.url);
        const a = document.createElement("a");
        a.className = "btn-sm get" + (got ? " got" : "");
        a.href = f.url;
        a.download = f.name;
        const num = it.files.length > 1 ? ` ${n + 1}` : "";
        a.textContent = got ? `İndirildi${num}` : `İndir${num}`;
        a.addEventListener("click", () => setTimeout(() => markGot(f.url), 0));
        row.actions.appendChild(a);
      });
    } else if (it.status === "error" && it.can_retry) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "btn-sm";
      b.textContent = "Tekrar dene";
      b.addEventListener("click", () => retry(it.id, b));
      row.actions.appendChild(b);
    }
  }

  function render(job) {
    paintJobSlots(job.items);
    job.items.forEach((it) => {
      const row = state.rows.get(it.id);
      if (row) renderRow(row, it);
    });

    const total = job.items.length;
    const done = job.items.filter((i) => i.status === "done").length;
    const failed = job.items.filter((i) => i.status === "error").length;
    const files = job.items.reduce((a, i) => a + (i.status === "done" ? i.files.length : 0), 0);

    if (!job.finished) {
      el.summary.textContent = `${done} / ${total} hazır` + (failed ? `, ${failed} hata` : "");
    } else if (!failed) {
      el.summary.textContent = `Hepsi hazır: ${files} video.`;
    } else if (!done) {
      el.summary.textContent = "Hiçbir video indirilemedi.";
    } else {
      el.summary.textContent = `${files} video hazır, ${failed} link indirilemedi.`;
    }

    renderAllButton(job, files);

    el.leftover.hidden = !state.leftover.length;
    el.leftover.textContent = `Kalan ${state.leftover.length} linke geç`;
    const minutes = Math.max(1, Math.round(job.expires_in / 60));
    el.expires.textContent = `Dosyalar ${minutes} dakika sonra sunucudan silinir.`;
  }

  // --- MP4'leri tek tek indirme ----------------------------------------
  const readyFiles = (job) =>
    job.items.flatMap((i) => (i.status === "done" ? i.files : []));

  function renderAllButton(job, total) {
    el.allHint.hidden = total < 2;
    if (state.busy) return;
    const pending = readyFiles(job).filter((f) => !state.got.has(f.url)).length;
    el.all.disabled = total === 0;
    if (total === 0) {
      el.all.textContent = job.finished ? "İndirilecek video yok" : "Videolar hazırlanıyor…";
    } else if (pending === 0) {
      el.all.textContent = job.finished ? "Hepsini yeniden indir" : "Hazır olanlar indirildi";
      el.all.disabled = !job.finished;
    } else if (state.got.size) {
      el.all.textContent = `Kalan ${pending} videoyu indir`;
    } else {
      el.all.textContent = job.finished ? `${pending} videoyu indir` : `Hazır ${pending} videoyu indir`;
    }
  }

  function markGot(url) {
    if (state.got.has(url) || !state.job) return;
    state.got.add(url);
    session.set(`kepce.got.${state.job.id}`, JSON.stringify([...state.got]));
    render(state.job);
  }

  function saveFile(f) {
    const a = document.createElement("a");
    a.href = f.url;
    a.download = f.name;
    a.hidden = true;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  async function downloadAll() {
    if (!state.job || state.busy) return;
    const all = readyFiles(state.job);
    let queue = all.filter((f) => !state.got.has(f.url));
    if (!queue.length) queue = all; // hepsi inmişse yeniden indir
    if (!queue.length) return;
    state.busy = true;
    el.all.disabled = true;
    for (let i = 0; i < queue.length; i++) {
      el.all.textContent = `İndiriliyor ${i + 1} / ${queue.length}`;
      saveFile(queue[i]);
      state.got.add(queue[i].url);
      // Tarayıcılar art arda gelen indirmeleri aralıklı ister.
      if (i < queue.length - 1) await sleep(700);
    }
    session.set(`kepce.got.${state.job.id}`, JSON.stringify([...state.got]));
    state.busy = false;
    render(state.job);
  }

  function poll(delay = 1000) {
    clearTimeout(state.timer);
    state.timer = setTimeout(async () => {
      if (state.phase !== "results" || !state.job) return;
      try {
        const res = await fetch(`/api/jobs/${state.job.id}`, { cache: "no-store" });
        if (res.status === 404) return expired();
        if (!res.ok) throw new Error(String(res.status));
        const job = await res.json();
        state.fails = 0;
        state.job = job;
        render(job);
        if (!job.finished) poll();
      } catch {
        state.fails += 1;
        poll(Math.min(1000 * 2 ** state.fails, 8000));
      }
    }, delay);
  }

  async function retry(itemId, button) {
    button.disabled = true;
    try {
      const res = await fetch(`/api/jobs/${state.job.id}/items/${itemId}/retry`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (res.status === 404 && !data.id) return expired();
      if (!res.ok) {
        button.disabled = false;
        const row = state.rows.get(itemId);
        if (row) row.status.textContent = data.error || "Yeniden denenemedi.";
        return;
      }
      state.job = data;
      render(data);
      poll(800);
    } catch {
      button.disabled = false;
    }
  }

  function backToInput(text, note) {
    clearTimeout(state.timer);
    if (state.job) session.del(`kepce.got.${state.job.id}`);
    state.job = null;
    state.got = new Set();
    session.del("kepce.job");
    setPhase("input");
    el.links.value = text;
    paintInputSlots(0);
    onInput();
    if (note) setNotice(note, true);
  }

  function expired() {
    const rest = state.leftover.join("\n");
    state.leftover = [];
    session.del("kepce.leftover");
    backToInput(rest, "Bu listenin süresi dolmuş. Linkleri yeniden yapıştır.");
  }

  // --- olaylar ---------------------------------------------------------
  el.links.addEventListener("input", onInput);
  el.links.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !el.go.disabled) start();
  });
  el.go.addEventListener("click", start);
  el.clear.addEventListener("click", () => {
    el.links.value = "";
    onInput();
    el.links.focus();
  });
  if (!navigator.clipboard || !navigator.clipboard.readText) el.paste.hidden = true;
  el.paste.addEventListener("click", async () => {
    try {
      const text = (await navigator.clipboard.readText()).trim();
      if (!text) return setNotice("Panoda yapıştırılacak metin yok.");
      const current = el.links.value.trim();
      el.links.value = current ? `${current}\n${text}` : text;
      onInput();
    } catch {
      el.links.focus();
      setNotice("Tarayıcı panoya erişim izni vermedi. Kutuya basılı tutup Yapıştır'ı seçebilirsin.");
    }
  });
  el.all.addEventListener("click", downloadAll);
  el.again.addEventListener("click", () => {
    state.leftover = [];
    session.del("kepce.leftover");
    backToInput("");
    el.links.focus();
  });
  el.leftover.addEventListener("click", () => {
    const rest = state.leftover.join("\n");
    state.leftover = [];
    session.del("kepce.leftover");
    backToInput(rest);
  });

  // --- sayfa yenilenirse kaldığı yerden devam ---------------------------
  (async () => {
    state.leftover = (session.get("kepce.leftover") || "").split("\n").filter(Boolean);
    const saved = session.get("kepce.job");
    if (saved) {
      try {
        const res = await fetch(`/api/jobs/${saved}`, { cache: "no-store" });
        if (res.ok) return showResults(await res.json());
      } catch { /* aşağıda giriş ekranına dön */ }
      session.del("kepce.job");
    }
    onInput();
  })();
})();
