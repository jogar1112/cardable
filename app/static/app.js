"use strict";
// Cardable v0.1 client. The server is the dealer: this client only renders
// the per-viewer state it is sent. It never holds hidden information.
const $ = (id) => document.getElementById(id);
let token = localStorage.getItem("cardable_token") || "";
let playerName = localStorage.getItem("cardable_name") || "";
let ws = null, state = null, roomCode = "";
let selectedStack = null, linkMode = "instant";
let library = [], decks = [];

async function api(path, opts = {}) {
  const r = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", "X-Player-Token": token, ...(opts.headers || {}) },
  });
  if (!r.ok) throw new Error((await r.text()) || r.status);
  return r.json();
}

// ---------------------------------------------------------- playing-card faces (drawn, no art assets)
const PIPS = {
  "A": [[50, 50]], "2": [[50, 22], [50, 78]], "3": [[50, 22], [50, 50], [50, 78]],
  "4": [[28, 22], [72, 22], [28, 78], [72, 78]],
  "5": [[28, 22], [72, 22], [50, 50], [28, 78], [72, 78]],
  "6": [[28, 22], [72, 22], [28, 50], [72, 50], [28, 78], [72, 78]],
  "7": [[28, 22], [72, 22], [50, 36], [28, 50], [72, 50], [28, 78], [72, 78]],
  "8": [[28, 22], [72, 22], [50, 36], [28, 50], [72, 50], [50, 64], [28, 78], [72, 78]],
  "9": [[28, 20], [72, 20], [28, 40], [72, 40], [50, 50], [28, 60], [72, 60], [28, 80], [72, 80]],
  "10": [[28, 20], [72, 20], [50, 30], [28, 40], [72, 40], [28, 60], [72, 60], [50, 70], [28, 80], [72, 80]],
};
function playingSVG(card) {
  const red = card.suit === "♥" || card.suit === "♦";
  const color = red ? "#b01e1e" : "#14141c";
  if (card.rank === "JOKER") {
    return `<svg class="pcard" viewBox="0 0 100 140"><rect width="100" height="140" fill="#f7f0dc"/><text x="50" y="60" font-size="34" text-anchor="middle">🃏</text><text x="50" y="95" font-size="13" text-anchor="middle" fill="${color}" font-weight="bold">JOKER</text></svg>`;
  }
  let pips = "";
  if (PIPS[card.rank]) {
    pips = PIPS[card.rank].map(([x, y]) => `<text x="${x}" y="${y + 6}" font-size="17" text-anchor="middle" fill="${color}">${card.suit}</text>`).join("");
  } else {
    pips = `<text x="50" y="86" font-size="44" text-anchor="middle" fill="${color}">${card.rank}</text><text x="50" y="112" font-size="22" text-anchor="middle" fill="${color}">${card.suit}</text>`;
  }
  return `<svg class="pcard" viewBox="0 0 100 140"><rect width="100" height="140" fill="#f7f0dc"/>` +
    `<text x="7" y="19" font-size="15" font-weight="bold" fill="${color}">${card.rank}</text>` +
    `<text x="7" y="35" font-size="13" fill="${color}">${card.suit}</text>${pips}` +
    `<text x="93" y="128" font-size="15" font-weight="bold" text-anchor="end" fill="${color}">${card.rank}${card.suit}</text></svg>`;
}
function faceHTML(card, glanceField) {
  let inner;
  if (card.kind === "playing") inner = playingSVG(card);
  else if (card.image) inner = `<img class="faceimg" src="${card.image}" alt="">`;
  else inner = `<div style="padding:16px 4px;text-align:center;color:#111;font-weight:bold">${card.name || "Card"}</div>`;
  const glance = glanceField === "rank_suit" ? (card.primary || "") : (card.primary || "");
  return `<div class="face">${inner}${glance ? `<div class="glance">${glance}</div>` : ""}<div class="gname">${card.name || ""}</div></div>`;
}

// ---------------------------------------------------------- boot / lobby
async function boot() {
  const b = await (await fetch("/api/build")).json();
  $("buildFooter").textContent = b.build;
  const profs = await (await fetch("/api/profiles")).json();
  $("profileSelect").innerHTML = profs.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
  if (playerName) $("nameInput").value = playerName;
  [4, 6, 8, 10, 100, 12, 20].forEach((s) => {
    const btn = document.createElement("button");
    btn.className = "btn small"; btn.textContent = s === 100 ? "d%" : "d" + s;
    btn.onclick = () => send({ type: "spawn_die", sides: s });
    $("diceBtns").appendChild(btn);
  });
}
async function ensurePlayer() {
  if (token) return;
  playerName = $("nameInput").value.trim() || "Player";
  const p = await api("/api/players", { method: "POST", body: JSON.stringify({ name: playerName }) });
  token = p.token;
  localStorage.setItem("cardable_token", token);
  localStorage.setItem("cardable_name", playerName);
  const s = await api("/api/settings");
  linkMode = s.link_mode || "instant";
  $("linkMode").value = linkMode;
}
async function createRoom() {
  await ensurePlayer();
  const r = await api("/api/rooms", { method: "POST", body: JSON.stringify({ profile_id: $("profileSelect").value }) });
  connect(r.code);
}
async function joinRoom() {
  await ensurePlayer();
  connect($("codeInput").value.trim().toUpperCase());
}
function connect(code) {
  roomCode = code;
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/table/${code}?token=${encodeURIComponent(token)}`);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "state") { state = msg; render(); }
    else if (msg.type === "search_result") renderDeckView(msg);
    else if (msg.type === "error") alert(msg.message);
  };
  ws.onclose = () => { $("roomInfo").textContent = `table ${code} — disconnected (rejoin to reclaim your seat)`; };
}
function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

// ---------------------------------------------------------- render
function render() {
  $("lobby").classList.add("hidden");
  $("game").classList.remove("hidden");
  $("roomInfo").textContent = `table ${state.code} · ${state.profile_name} · ${state.phase}`;
  $("seatsBar").innerHTML = state.seats.map((s) => {
    if (!s.name) return `<div class="seat">Seat ${s.seat + 1}: —</div>`;
    return `<div class="seat ${s.is_you ? "me" : ""} ${state.turn_seat === s.seat ? "turn" : ""}">${s.is_you ? "▶ " : ""}${s.name} · 🂠 ${s.hand_count}${s.connected ? "" : ' <span class="off">(away)</span>'}${s.searching ? ` · 🔍 searching ${s.searching}…` : ""}</div>`;
  }).join("");
  $("turnBanner").textContent = state.phase === "playing"
    ? (state.turn_seat === state.your_seat ? "★ YOUR TURN ★" : `Turn: seat ${state.turn_seat + 1}`) : "SETUP — drag your stacks into place";
  const felt = $("felt");
  felt.innerHTML = "";
  state.stacks.forEach((st) => {
    const el = document.createElement("div");
    el.className = "stack" + (selectedStack === st.id ? " sel" : "");
    el.style.left = st.x + "%"; el.style.top = st.y + "%";
    el.innerHTML = `<div class="sname">${st.name}</div><div class="scount">${st.count}</div>` +
      (st.top ? `<div class="stop">${st.top.primary || st.top.name}</div>` : "") +
      (st.owner !== null ? `<div style="font-size:9px">seat ${st.owner + 1}</div>` : "");
    el.onclick = () => { selectedStack = st.id; renderTools(); render(); };
    makeDraggable(el, (x, y) => { if (state.phase === "setup") send({ type: "move_stack", stack_id: st.id, x, y }); });
    felt.appendChild(el);
  });
  state.table_cards.forEach((tc) => {
    const el = document.createElement("div");
    el.className = "tcard" + (tc.tapped ? " tapped" : "");
    el.style.left = tc.x + "%"; el.style.top = tc.y + "%";
    el.dataset.uid = tc.uid;
    el.innerHTML = tc.face_up || tc.known_to_you ? faceHTML(tc, state.glance) : `<div class="back"></div>`;
    el.onclick = () => {};
    el.ondblclick = () => examine(tc);
    makeDraggable(el, (x, y) => send({ type: "move_card", uid: tc.uid, x, y }));
    addCardButtons(el, tc);
    felt.appendChild(el);
  });
  state.dice.forEach((d) => {
    const el = document.createElement("div");
    el.className = "die"; el.style.left = d.x + "%"; el.style.top = d.y + "%";
    el.innerHTML = `<div class="dval">${d.label === "coin" ? (d.value === 1 ? "H" : "T") : d.value}</div><div class="dlab">${d.label}${d.on_card ? " · on card" : ""}</div>`;
    el.onclick = () => { el.classList.add("rolling"); send({ type: "roll_die", die_id: d.id }); };
    makeDraggable(el, (x, y, ev) => {
      const under = document.elementFromPoint(ev.clientX, ev.clientY);
      const cardEl = under && under.closest ? under.closest(".tcard") : null;
      send({ type: "move_die", die_id: d.id, x, y });
      if (cardEl) send({ type: "park_die", die_id: d.id, uid: cardEl.dataset.uid });
      else send({ type: "park_die", die_id: d.id, uid: null });
    });
    felt.appendChild(el);
  });
  $("hand").innerHTML = "";
  state.hand.forEach((c) => {
    const el = document.createElement("div");
    el.className = "hcard"; el.innerHTML = faceHTML(c, state.glance);
    el.onclick = () => send({ type: "play_card", uid: c.uid, face_up: true, x: 50, y: 50 });
    el.ondblclick = (e) => { e.stopPropagation(); examine(c); };
    el.oncontextmenu = (e) => { e.preventDefault(); send({ type: "play_card", uid: c.uid, face_up: false, x: 50, y: 45 }); };
    $("hand").appendChild(el);
  });
  $("handCount").textContent = `(${state.hand.length})`;
  $("log").innerHTML = state.log.slice(-8).map((l) => `<div>${l}</div>`).join("");
  renderTools();
}
function addCardButtons(el, tc) {
  el.title = "double-tap: examine · buttons appear on long press";
  el.oncontextmenu = (e) => {
    e.preventDefault();
    const menu = [["Flip", () => send({ type: "flip_card", uid: tc.uid })],
                  ["Take", () => send({ type: "take_card", uid: tc.uid })],
                  ["Examine", () => examine(tc)]];
    const pick = prompt(menu.map((m, i) => `${i + 1}. ${m[0]}`).join("\n"), "3");
    const m = menu[parseInt(pick, 10) - 1];
    if (m) m[1]();
  };
}
function renderTools() {
  const t = $("stackTools");
  if (!selectedStack) { t.innerHTML = "<span class='hint'>Tap a stack for its tools.</span>"; return; }
  const st = state.stacks.find((s) => s.id === selectedStack);
  if (!st) { t.innerHTML = ""; return; }
  t.innerHTML = `<b>${st.name}</b> (${st.count}) `;
  const mk = (label, fn) => { const b = document.createElement("button"); b.className = "btn small"; b.textContent = label; b.onclick = fn; t.appendChild(b); };
  mk("Draw 1", () => send({ type: "draw", stack_id: st.id, count: 1 }));
  mk("Draw 7", () => send({ type: "draw", stack_id: st.id, count: 7 }));
  mk("Shuffle", () => send({ type: "shuffle", stack_id: st.id }));
  if (st.role === "deck") mk("Load built-in 52", () => send({ type: "load_builtin", stack_id: st.id, jokers: true, shuffle: true }));
  if (st.role === "deck" && (st.owner === state.your_seat || st.owner === null)) mk("🔍 Search deck", () => openDeckView({ action: "search", count: null, filter: "", tail: null }, st));
  decks.forEach((d) => mk(`Bring “${d.name}”`, () => send({ type: "bring_deck", deck_id: d.id, stack_id: st.id })));
}

// ---------------------------------------------------------- dragging (setup stacks, cards, dice)
// Finger drags must move the PIECE, never the page: the draggable classes
// carry `touch-action:none` in CSS, we capture the pointer, and the piece
// follows the finger live instead of teleporting on release.
function makeDraggable(el, onDrop) {
  let sx = 0, sy = 0, moved = false, pid = null;
  el.addEventListener("click", (e) => {
    // a real drag also produces a click on release -- swallow that one,
    // except for stacks, where selecting on drop is convenient
    if (el._supClick && !el.classList.contains("stack")) {
      el._supClick = false; e.stopImmediatePropagation(); e.preventDefault();
    }
  }, true);
  el.addEventListener("pointerdown", (e) => {
    pid = e.pointerId; sx = e.clientX; sy = e.clientY; moved = false;
    try { el.setPointerCapture(pid); } catch (_) {}
  });
  el.addEventListener("pointermove", (e) => {
    if (pid !== e.pointerId) return;
    if (Math.abs(e.clientX - sx) + Math.abs(e.clientY - sy) > 8) moved = true;
    if (moved) {
      const felt = $("felt").getBoundingClientRect();
      el.style.left = Math.max(0, Math.min(100, ((e.clientX - felt.left) / felt.width) * 100)) + "%";
      el.style.top = Math.max(0, Math.min(100, ((e.clientY - felt.top) / felt.height) * 100)) + "%";
    }
  });
  el.addEventListener("pointerup", (e) => {
    if (pid !== e.pointerId) return; pid = null;
    if (!moved) return;
    el._supClick = true; setTimeout(() => { el._supClick = false; }, 120);
    const felt = $("felt").getBoundingClientRect();
    const x = Math.max(0, Math.min(100, ((e.clientX - felt.left) / felt.width) * 100));
    const y = Math.max(0, Math.min(100, ((e.clientY - felt.top) / felt.height) * 100));
    onDrop(x, y, e);
  });
  el.addEventListener("pointercancel", () => { pid = null; });
}

// ---------------------------------------------------------- examine + phrase links
let examCardData = null, lastMatches = [];
async function examine(card) {
  if (card.known_to_you === false && !card.name) return; // never foreground a hidden face
  examCardData = card;
  $("examCard").innerHTML = faceHTML(card, state ? state.glance : "primary");
  const text = card.text || "";
  const box = $("examText");
  box.innerHTML = `<b>${card.name || ""}</b>${card.primary ? ` · ${card.primary}` : ""}${card.type_line ? `\n${escapeHtml(card.type_line)}` : ""}\n`;
  if (text) {
    const m = await api("/api/phrases/match", { method: "POST", body: JSON.stringify({ text }) });
    lastMatches = m.matches;
    let html = "", last = 0;
    m.matches.forEach((mm, idx) => {
      html += escapeHtml(text.slice(last, mm.start));
      html += `<span class="plink" data-idx="${idx}">${escapeHtml(mm.phrase)}</span>`;
      last = mm.end;
    });
    html += escapeHtml(text.slice(last));
    box.innerHTML += html;
    box.querySelectorAll(".plink").forEach((el) => wireLink(el, lastMatches[parseInt(el.dataset.idx, 10)]));
  } else box.innerHTML += "(no text)";
  $("examine").classList.remove("hidden");
}
function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
function wireLink(el, match) {
  let timer = null, armed = false;
  const bar = $("holdbar"), fill = $("holdfill");
  el.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    if (linkMode === "confirm" && armed) { fireLink(match); armed = false; el.classList.remove("armed"); return; }
    bar.style.visibility = "visible"; fill.style.width = "0%";
    const t0 = Date.now();
    timer = setInterval(() => {
      const pct = Math.min(100, ((Date.now() - t0) / 600) * 100);
      fill.style.width = pct + "%";
      if (pct >= 100) {
        clearInterval(timer); bar.style.visibility = "hidden";
        if (linkMode === "instant") fireLink(match);
        else { armed = true; el.classList.add("armed"); }
      }
    }, 30);
  });
  ["pointerup", "pointerleave", "pointercancel"].forEach((ev) =>
    el.addEventListener(ev, () => { if (timer) clearInterval(timer); bar.style.visibility = "hidden"; fill.style.width = "0%"; }));
}
function myDeckStack() {
  if (!state) return null;
  return state.stacks.find((s) => s.role === "deck" && (s.owner === state.your_seat || s.owner === null));
}
function fireLink(match) {
  const action = match.action, count = match.count || 1, sides = match.sides || 20;
  const deck = myDeckStack();
  if (action === "search" || action === "peek") { openDeckView(match); return; }
  if (action === "draw" && deck) send({ type: "draw", stack_id: deck.id, count });
  else if (action === "shuffle" && deck) send({ type: "shuffle", stack_id: deck.id });
  else if (action === "coin") {
    const coin = state.dice.find((d) => d.label === "coin");
    if (coin) send({ type: "roll_die", die_id: coin.id });
    else { send({ type: "spawn_die", sides: 2 }); setTimeout(() => { const c = state.dice.find((d) => d.label === "coin"); if (c) send({ type: "roll_die", die_id: c.id }); }, 350); }
  } else if (action === "roll") {
    const die = state.dice.find((d) => d.sides === sides) || state.dice[0];
    if (die) send({ type: "roll_die", die_id: die.id });
    else { send({ type: "spawn_die", sides }); setTimeout(() => { const d2 = state.dice.find((d) => d.sides === sides); if (d2) send({ type: "roll_die", die_id: d2.id }); }, 350); }
  }
  $("examine").classList.add("hidden");
}

// ---------------------------------------------------------- deck view (keyword search / peek)
// The server holds the deck and flags the matches; this view only renders
// the direct reply meant for the searcher. Opponents see "searching...".
let dv = null;
function openDeckView(match, stackOverride) {
  const deck = stackOverride || myDeckStack();
  if (!deck) { $("examine").classList.add("hidden"); return; }
  dv = {
    stackId: deck.id, stackName: deck.name, mode: match.action,
    cap: match.count || null, tail: match.tail || null,
    topN: match.action === "peek" ? (match.count || 1) : null,
    taken: new Set(), takenCount: 0, cards: [],
  };
  $("examine").classList.add("hidden");
  $("deckview").classList.remove("hidden");
  $("dvTitle").textContent = match.action === "peek"
    ? `Top ${dv.topN} of ${deck.name}` : `Searching ${deck.name}`;
  $("dvManualRow").style.display = match.action === "search" ? "" : "none";
  $("dvFilter").value = match.filter || "";
  $("dvGrid").innerHTML = "<div class='hint'>looking…</div>";
  $("dvTerms").textContent = "";
  updateDvTally();
  renderDvTail();
  send({ type: "searching", stack_id: deck.id, mode: match.action });
  requestSearch();
}
function requestSearch() {
  if (!dv) return;
  dv.taken = new Set();
  send({ type: "search_query", stack_id: dv.stackId, mode: dv.mode,
         top_n: dv.topN, filter: $("dvFilter").value });
}
function filterTerms(groups) {
  if (!groups) return "";
  const terms = [
    ...(groups.types || []), ...(groups.traits || []), ...(groups.colors || []),
    ...(groups.names || []), ...(groups.qualifiers || []),
    ...(groups.not_types || []).map((t) => "non-" + t),
    ...(groups.numbers || []).map((n) => `${n.field.replace("_", " ")} ${n.value} or ${n.op === "<=" ? "less" : "more"}`),
  ];
  return terms.length ? "filter: " + terms.join(" · ") : "no filter — everything is lit";
}
function renderDeckView(msg) {
  if (!dv || msg.stack_id !== dv.stackId) return;
  if (msg.denied) { $("dvGrid").innerHTML = "<div class='hint'>That stack isn't yours to search.</div>"; return; }
  dv.cards = msg.cards;
  $("dvTerms").textContent = filterTerms(msg.groups);
  renderDvGrid();
}
function renderDvGrid() {
  const grid = $("dvGrid");
  grid.innerHTML = "";
  dv.cards.forEach((c) => {
    const el = document.createElement("div");
    el.className = "dvcard" + (c.match ? " match" : " dim") + (dv.taken.has(c.uid) ? " taken" : "");
    el.innerHTML = faceHTML(c, state ? state.glance : "primary");
    el.title = c.type_line || c.name || "";
    el.onclick = () => takeDvCard(c.uid);
    grid.appendChild(el);
  });
  if (!dv.cards.length) grid.innerHTML = "<div class='hint'>Nothing here.</div>";
  const lit = dv.cards.filter((c) => c.match).length;
  $("dvTerms").dataset.lit = lit;
  updateDvTally(lit);
}
function updateDvTally(lit) {
  if (!dv) return;
  const litTxt = lit !== undefined ? ` · ${lit} lit` : "";
  if (dv.mode === "peek") $("dvTally").textContent = `taken ${dv.takenCount} of top ${dv.topN}${litTxt}`;
  else $("dvTally").textContent = `taken ${dv.takenCount}${dv.cap ? ` (card said up to ${dv.cap} — your call, as always)` : ""}${litTxt}`;
}
function takeDvCard(uid) {
  if (!dv || dv.taken.has(uid)) return;
  send({ type: "take_from_stack", stack_id: dv.stackId, uid });
  dv.taken.add(uid); dv.takenCount += 1;
  renderDvGrid();
}
function renderDvTail() {
  const b = $("dvTail");
  if (!dv || !dv.tail) { b.classList.add("hidden"); return; }
  b.classList.remove("hidden");
  if (dv.tail === "shuffle") {
    b.textContent = "Shuffle, then done";
    b.onclick = () => { send({ type: "shuffle", stack_id: dv.stackId }); closeDeckView(); };
  } else if (dv.tail === "recycle") {
    b.textContent = "Recycle the rest";
    b.onclick = () => {
      const rest = dv.cards.filter((c) => !dv.taken.has(c.uid)).map((c) => c.uid);
      if (rest.length) send({ type: "recycle_rest", stack_id: dv.stackId, uids: rest });
      closeDeckView();
    };
  }
}
function closeDeckView() {
  if (dv) send({ type: "searching", stack_id: null });
  dv = null;
  $("deckview").classList.add("hidden");
}
async function refreshLibrary() {
  library = await api("/api/library");
  decks = await api("/api/decks");
  $("libList").innerHTML = "";
  library.forEach((c) => {
    const row = document.createElement("div");
    row.className = "libcard";
    row.innerHTML = `<img src="${c.image_path}"><div style="flex:1">
      <label><input type="checkbox" class="deckpick" value="${c.id}"> in deck</label>
      <input data-f="name" placeholder="Name" value="${(c.name || "").replace(/"/g, "&quot;")}">
      <input data-f="primary" placeholder="Primary number (HP / cost / rank)" value="${(c.primary_number || "").replace(/"/g, "&quot;")}">
      <input data-f="typeline" placeholder="Type line (Creature — Elf · Basic Land — Forest)" value="${(c.type_line || "").replace(/"/g, "&quot;")}">
      <textarea data-f="text" placeholder="Card text (phrase links live here)">${c.text || ""}</textarea>
      <button class="btn small save">Save</button> <button class="btn small sf">Scryfall lookup</button></div>`;
    row.querySelector(".save").onclick = async () => {
      await api(`/api/library/${c.id}`, { method: "PUT", body: JSON.stringify({
        name: row.querySelector('[data-f="name"]').value,
        primary: row.querySelector('[data-f="primary"]').value,
        type_line: row.querySelector('[data-f="typeline"]').value,
        text: row.querySelector('[data-f="text"]').value }) });
      refreshLibrary();
    };
    row.querySelector(".sf").onclick = async () => {
      try { await api(`/api/library/${c.id}/scryfall`, { method: "POST" }); refreshLibrary(); }
      catch (e) { alert("Scryfall: " + e.message); }
    };
    $("libList").appendChild(row);
  });
  $("deckList").innerHTML = decks.map((d) => `<div>🂡 ${d.name} — ${d.card_ids.length} cards</div>`).join("");
}

// ---------------------------------------------------------- wire up
$("createBtn").onclick = () => createRoom().catch((e) => alert(e.message));
$("joinBtn").onclick = () => joinRoom().catch((e) => alert(e.message));
$("startBtn").onclick = () => send({ type: "start_game" });
$("passBtn").onclick = () => send({ type: "pass_turn" });
$("coinBtn").onclick = () => {
  const coin = state && state.dice.find((d) => d.label === "coin");
  if (coin) send({ type: "roll_die", die_id: coin.id }); else send({ type: "spawn_die", sides: 2 });
};
$("customDieBtn").onclick = () => {
  const n = parseInt($("customSides").value, 10);
  if (n >= 2 && n <= 1000) send({ type: "spawn_die", sides: n });
};
$("examClose").onclick = () => $("examine").classList.add("hidden");
$("dvClose").onclick = () => closeDeckView();
$("dvFilterBtn").onclick = () => requestSearch();
$("dvFilter").addEventListener("keydown", (e) => { if (e.key === "Enter") requestSearch(); });
$("libBtn").onclick = async () => { await ensurePlayer(); await refreshLibrary(); $("library").classList.remove("hidden"); };
$("libClose").onclick = () => $("library").classList.add("hidden");
$("setBtn").onclick = async () => { await ensurePlayer(); $("settings").classList.remove("hidden"); };
$("setClose").onclick = () => $("settings").classList.add("hidden");
$("linkMode").onchange = async () => { linkMode = $("linkMode").value; await api("/api/settings", { method: "PUT", body: JSON.stringify({ link_mode: linkMode }) }); };
$("uploadInput").onchange = async () => {
  const f = $("uploadInput").files[0];
  if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  const r = await fetch("/api/library/upload", { method: "POST", headers: { "X-Player-Token": token }, body: fd });
  if (!r.ok) { alert(await r.text()); return; }
  refreshLibrary();
};
$("makeDeckBtn").onclick = async () => {
  const ids = [...document.querySelectorAll(".deckpick:checked")].map((c) => parseInt(c.value, 10));
  if (!ids.length) { alert("tick at least one card"); return; }
  await api("/api/decks", { method: "POST", body: JSON.stringify({ name: $("deckName").value || "Deck", card_ids: ids }) });
  refreshLibrary();
};
boot();
