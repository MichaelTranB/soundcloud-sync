/* The Crate's guided tour: one script for both pages (The Crate "/" and the Library Manager "/dj").
 *
 * - Each step highlights a real button or section and says, in a line or two, what it does and when.
 * - Next from the last step on "/" carries on at the first step of "/dj" (the address ends in #tour), and Back from
 *   there returns to the last step of "/".
 * - A step whose element isn't on screen on this setup (no USB, nothing synced yet) is skipped, or shown with a short
 *   note when it has one: it never points at nothing.
 * - Who has seen it lives on the server (tour.py, tour.json), per page. A first-time user gets it by itself; an
 *   install that already worked gets a one-line offer instead (or nothing). "Take the tour" replays it any time.
 * - Keys: ← → move, Esc skips, Tab stays on the card. Motion is off when the system asks for reduced motion.
 */
(() => {
  'use strict';
  if (window.__crateTour) return;
  window.__crateTour = true;

  const PAGE = location.pathname.replace(/\/+$/, '') === '/dj' ? 'dj' : 'home';
  const NAME = { home: 'The Crate', dj: 'Library Manager' };
  const q = s => document.querySelector(s);
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const phone = () => innerWidth < 700;

  // ---- what each step points at -------------------------------------------------------------------------------
  const field = sel => () => { const e = q(sel); return e && e.closest('.field'); };
  // A section on the Library Manager page is a small heading row (.hd) followed by its content.
  const section = sel => () => {
    const e = q(sel); let h = e && e.previousElementSibling;
    while (h && !h.classList.contains('hd')) h = h.previousElementSibling;
    return e && (h ? [h, e] : e);
  };

  const STEPS = {
    home: [
      { title: 'Welcome to The Crate', text: 'It gets your playlists onto your Mac in top quality, then onto your DJ USB. A one-minute look around.' },
      { target: () => q('#start'), title: 'Your checklist', text: 'Each step ticks itself when it\'s done. Hide it any time; the Setup button brings it back.' },
      { target: field('#url'), title: 'Add a playlist', text: 'Paste a SoundCloud, Spotify or Apple Music link and press Add. Tap a saved one to sync it.' },
      { target: () => { const e = q('#profile'); return e && e.closest('details'); }, title: 'Or find yours on SoundCloud',
        text: 'Open this and type your SoundCloud name to list every playlist you have. It uses the sign-in already in your browser.' },
      { target: field('#liked'), title: 'Spotify Liked Songs', text: 'Paste them once. Each sync fetches the next batch, EDM first, and always leaves space free on your Mac.' },
      { target: field('#usb'), title: 'Your DJ USB', text: 'Pick it and new songs copy over after every sync and whenever you plug it in. It only adds, never deletes.' },
      { target: field('#slskUser'), title: 'Soulseek', text: 'Finds what SoundCloud won\'t give you, lossless or 320 kbps only. Sign in once; it only ever downloads.' },
      { target: field('#syncTime'), title: 'Daily sync', text: 'Pick the time. Keep your Mac on then; if it\'s asleep, it syncs when it wakes.' },
      { target: () => q('#sync'), title: 'Sync Now', text: 'Gets new songs right away, then updates your USB and DJ lists. The first one takes a while.' },
      { target: () => q('#q'), title: 'Your tracks', text: 'Search both lists. On the left, what\'s on your Mac. On the right, what\'s left to find, with free links and shops.' },
      { target: () => q('#djOpen'), title: 'Next: the Library Manager', next: 'Show me',
        text: 'Your songs get tempo, key and genres, and go onto your decks. That\'s the other half of the tour.' },
    ],
    dj: [
      { title: 'The Library Manager', text: 'Every song with its tempo, key and genres, put onto your decks by itself after each sync.' },
      { target: () => q('.strip'), title: 'At a glance', text: 'How many songs, how many are sorted into genres, and whether your decks are up to date.' },
      { target: section('#decks'), ready: () => q('#decks') && q('#decks').children.length,
        note: 'Your decks (Engine DJ, rekordbox, Serato) show here once songs are synced and a USB is chosen.',
        title: 'Your decks', text: 'Where your songs stand in each DJ app. They update by themselves; your own playlists are never touched.' },
      { target: section('#folders'), title: 'USB folders', text: 'One folder, or EDM and Other, or by genre. It asks before moving anything, and One folder puts it all back.' },
      { target: () => q('#club'), title: 'Club check', text: 'Tells you what a club\'s decks need from your USB before a gig.' },
      { target: () => q('#other'), title: 'Copy from another USB', text: 'A friend\'s USB shows up here. Tick what you want; it\'s only read, never changed.' },
      { target: section('#pills'), title: 'Genres', text: 'Each genre is a playlist on your decks. Tap one to see its songs; your pick always wins.' },
      { target: () => { const e = q('#doAiff'); return e && e.closest('.doit'); }, title: 'Fix up songs',
        text: 'Tick songs, then Convert to AIFF, Add cover & details, or Put on USB. Every change has Undo on its row.' },
      { target: () => q('#q'), title: 'Find a song', text: 'Search by song, artist, genre, key or format. Press ▶ on a song to hear it.' },
      { target: () => q('#run'), title: 'Update decks now', text: 'Sends new songs, genres, tempo and key to your USB and rekordbox. rekordbox has to be closed.' },
      { target: () => q('#optsOpen'), title: 'Options', text: 'Every switch lives here: what runs by itself, USB layout, cues. Each one can be changed back.' },
      { target: () => q('#faqLink'), title: 'Questions?', next: 'Done',
        text: 'The FAQ has search and a short answer for everything. "Take the tour" replays this any time.' },
    ],
  };

  // ---- helpers ------------------------------------------------------------------------------------------------
  // A closed <details> keeps its box but paints nothing inside it, so what sits in one (below its summary) is not on screen.
  const folded = e => { const d = e.closest('details:not([open])'); return !!d && !(e.closest('summary') && e.closest('summary').parentElement === d); };
  const shown = e => !!e && e.getClientRects().length > 0 && e.getBoundingClientRect().width > 0 && !folded(e);
  const asList = v => (Array.isArray(v) ? v : [v]).filter(Boolean);
  function union(els) {
    let t = Infinity, l = Infinity, b = -Infinity, r = -Infinity;
    for (const e of els) { const x = e.getBoundingClientRect(); t = Math.min(t, x.top); l = Math.min(l, x.left); b = Math.max(b, x.bottom); r = Math.max(r, x.right); }
    return { top: t, left: l, bottom: b, right: r, width: r - l, height: b - t };
  }
  // The steps that can be shown right now, with what each one points at (re-read every time: the page fills in late).
  function list() {
    const out = [];
    STEPS[PAGE].forEach((s, idx) => {
      if (!s.target) return out.push({ s, idx, els: [], text: s.text });
      const els = asList(s.target()).filter(shown);
      if (els.length && (!s.ready || s.ready())) return out.push({ s, idx, els, text: s.text });
      if (s.note) out.push({ s, idx, els: [], text: s.note });
    });
    return out;
  }
  const tell = page => fetch('/api/tour', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ page }), keepalive: true })
    .then(r => { if (!r.ok) throw new Error('tour: ' + r.status); })
    .catch(e => console.error('The tour could not be remembered:', e));

  // ---- the look: the page's own colours, set on the card and the highlight only ---------------------------------
  const css = document.createElement('style');
  css.textContent = `
  .tour-shield { position: fixed; inset: 0; z-index: 2147483000; }
  .tour-spot { position: fixed; z-index: 2147483001; pointer-events: none; border-radius: 16px; border: 2px solid var(--hot, #c8102e);
    box-shadow: 0 0 0 100vmax rgba(4, 4, 9, .74); transition: top .4s cubic-bezier(.4, 0, .2, 1), left .4s cubic-bezier(.4, 0, .2, 1),
    width .4s cubic-bezier(.4, 0, .2, 1), height .4s cubic-bezier(.4, 0, .2, 1), border-color .25s; }
  .tour-spot.none { border-color: transparent; }
  .tour-card { position: fixed; z-index: 2147483002; background: var(--panel, #15151d); color: var(--text, #f0eef8);
    border: 1px solid var(--line, #282834); border-radius: 18px; padding: 16px 18px 14px; box-shadow: 0 18px 50px rgba(0, 0, 0, .55);
    font: 15px/1.45 -apple-system, "Helvetica Neue", sans-serif; transition: top .4s cubic-bezier(.4, 0, .2, 1), left .4s cubic-bezier(.4, 0, .2, 1); }
  .tour-card:focus { outline: none; }
  .tour-root.track .tour-spot, .tour-root.track .tour-card { transition: none; }
  .tour-meta { display: flex; justify-content: space-between; gap: 12px; color: var(--dim, #a4a2b6); font-size: 12.5px; letter-spacing: .02em; }
  .tour-count { font-variant-numeric: tabular-nums; }
  .tour-bar { height: 3px; border-radius: 3px; background: var(--line, #282834); margin: 8px 0 12px; overflow: hidden; }
  .tour-bar i { display: block; height: 100%; background: var(--hot, #c8102e); width: 0; transition: width .4s ease; }
  .tour-body { transition: opacity .18s; }
  .tour-body.swap { opacity: 0; }
  .tour-card h2 { display: block; font-size: 18px; line-height: 1.25; margin: 0 0 4px; letter-spacing: -.01em; }
  .tour-card p { margin: 0; color: var(--dim, #a4a2b6); }
  .tour-btns { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 14px; }
  .tour-btns > span { display: flex; gap: 8px; }
  .tour-card button { font: inherit; font-weight: 700; font-size: 14.5px; border-radius: 999px; cursor: pointer; padding: 9px 18px;
    border: 1px solid var(--line, #282834); background: transparent; color: var(--text, #f0eef8); transform: none; }
  .tour-card button.tour-next { background: var(--hot, #c8102e); border-color: var(--hot, #c8102e); color: #fff; }
  .tour-card button.tour-skip { border: 0; padding: 9px 4px; color: var(--dim, #a4a2b6); font-weight: 600; }
  .tour-card button:focus-visible { outline: 2px solid var(--hot, #c8102e); outline-offset: 2px; }
  .tour-card [hidden] { display: none; }
  .tour-offer { display: flex; align-items: center; gap: 8px 14px; flex-wrap: wrap; margin: 20px 0 0; padding: 12px 16px;
    border: 1px solid var(--line, #282834); border-left: 3px solid var(--hot, #c8102e); border-radius: 12px; background: var(--panel, #15151d);
    color: var(--text, #f0eef8); font-size: 15px; }
  .tour-offer span { flex: 1 1 240px; }
  .tour-offer button { font: inherit; font-size: 14px; font-weight: 700; border-radius: 999px; cursor: pointer; padding: 8px 16px; border: 1px solid var(--line, #282834);
    background: transparent; color: var(--text, #f0eef8); }
  .tour-offer button.go { background: var(--hot, #c8102e); border-color: var(--hot, #c8102e); color: #fff; }
  @media (max-width: 699px) { .tour-card { padding: 14px 16px 12px; } .tour-card h2 { font-size: 17px; } }
  @media (prefers-reduced-motion: reduce) { .tour-spot, .tour-card, .tour-bar i, .tour-body { transition: none !important; } }`;
  document.head.appendChild(css);

  // ---- the tour -----------------------------------------------------------------------------------------------
  let T = null;

  function start(from, cameFrom) {
    if (T) return;
    const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt) e.textContent = txt; return e; };
    const root = el('div', 'tour-root'), shield = el('div', 'tour-shield'), spot = el('div', 'tour-spot none');
    const card = el('div', 'tour-card');
    card.setAttribute('role', 'dialog'); card.setAttribute('aria-modal', 'true'); card.setAttribute('aria-label', 'Tour of ' + NAME[PAGE]);
    card.tabIndex = -1;
    const where = el('span', '', NAME[PAGE]), count = el('span', 'tour-count'), bar = el('div', 'tour-bar'), fill = el('i');
    bar.appendChild(fill);
    const body = el('div', 'tour-body'), h = el('h2'), p = el('p');
    h.id = 'tourTitle'; p.id = 'tourText'; card.setAttribute('aria-labelledby', 'tourTitle'); card.setAttribute('aria-describedby', 'tourText');
    body.append(h, p);
    const meta = el('div', 'tour-meta'); meta.append(where, count);
    const skip = el('button', 'tour-skip', 'Skip tour'), back = el('button', 'tour-back', 'Back'), next = el('button', 'tour-next', 'Next');
    for (const b of [skip, back, next]) b.type = 'button';
    const nav = el('span'); nav.append(back, next);
    const btns = el('div', 'tour-btns'); btns.append(skip, nav);
    card.append(meta, bar, body, btns);
    root.append(shield, spot, card);
    document.body.appendChild(root);
    const main = q('main');
    if (main) main.inert = true;
    T = { root, spot, card, body, h, p, count, fill, back, next, main, opener: document.activeElement, cur: -1, token: 0,
          settling: false, pending: 0, item: null, cameFrom: !!cameFrom, leaving: false };
    skip.onclick = () => end(true);
    back.onclick = () => move(-1);
    next.onclick = () => move(1);
    document.addEventListener('keydown', onKey, true);
    addEventListener('resize', retrack);
    addEventListener('scroll', retrack, { passive: true });
    const L = list();
    show(from === 'last' ? L[L.length - 1] : L[0], false);
  }

  function end(markSeen) {
    if (!T || T.leaving) return;
    document.removeEventListener('keydown', onKey, true);
    removeEventListener('resize', retrack);
    removeEventListener('scroll', retrack);
    if (markSeen) tell(PAGE);
    T.root.remove();
    if (T.main) T.main.inert = false;
    const o = T.opener;
    T = null;
    if (o && document.contains(o) && o.focus) o.focus({ preventScroll: true });
  }

  function leaveTo(url, page) {
    if (page) tell(page);
    T.leaving = true;
    location.href = url;
  }

  function move(dir) {
    if (!T || T.leaving) return;
    const L = list();
    const target = dir > 0 ? L.find(x => x.idx > T.cur) : [...L].reverse().find(x => x.idx < T.cur);
    if (target) return show(target, true);
    if (dir > 0) return PAGE === 'home' ? leaveTo('/dj#tour', 'home') : end(true);
    if (PAGE === 'dj' && T.cameFrom) leaveTo('/#tour=last');
  }

  function show(item, animate) {
    if (!item) return end(false);
    const L = list(), rank = Math.max(0, L.findIndex(x => x.idx === item.idx));
    T.cur = item.idx; T.item = item;
    const apply = () => {
      T.h.textContent = item.s.title;
      T.p.textContent = item.text;
      T.count.textContent = `${rank + 1} of ${L.length}`;
      T.fill.style.width = ((rank + 1) / L.length * 100) + '%';
      const last = rank === L.length - 1;
      T.next.textContent = item.s.next || (last ? (PAGE === 'home' ? 'Library Manager' : 'Done') : 'Next');
      T.back.hidden = rank === 0 && !(PAGE === 'dj' && T.cameFrom);
      T.card.setAttribute('aria-label', `Tour of ${NAME[PAGE]}, step ${rank + 1} of ${L.length}`);
    };
    if (animate && !reduced()) {
      T.body.classList.add('swap');
      setTimeout(() => { if (!T) return; apply(); T.body.classList.remove('swap'); if (!T.settling && T.item === item) layout(true); }, 150);  // the card grew or shrank with the new words
    } else apply();
    place(item, animate);
    T.card.focus({ preventScroll: true });
  }

  async function place(item, animate) {
    const my = ++T.token;
    if (item.els.length) {
      await bringIntoView(item);
      if (!T || my !== T.token) return;
    }
    layout(animate);
  }

  function cardHeight() { return T.card.offsetHeight || 190; }

  function bringIntoView(item) {
    const r = union(item.els);
    const vh = innerHeight, ch = cardHeight();
    const room = phone() ? vh - ch - 30 : vh * 0.7;
    if (r.top >= 56 && r.bottom <= room) return Promise.resolve();
    const want = phone() ? 64 : (r.height < vh * 0.5 ? vh * 0.2 : 72);
    const max = document.documentElement.scrollHeight - vh;
    const to = Math.max(0, Math.min(scrollY + r.top - want, max));
    if (Math.abs(to - scrollY) < 2) return Promise.resolve();
    T.settling = true;
    scrollTo({ top: to, behavior: reduced() ? 'auto' : 'smooth' });
    return new Promise(done => {
      let last = -1, still = 0; const t0 = performance.now();
      const tick = () => {
        still = Math.abs(scrollY - last) < 0.5 ? still + 1 : 0; last = scrollY;
        if (still >= 5 || performance.now() - t0 > 1000) { if (T) T.settling = false; done(); } else requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }

  // The highlight goes to the element (clamped to the screen); the card goes below, above or beside it.
  function layout(animate) {
    if (!T) return;
    const vw = innerWidth, vh = innerHeight, ph = phone();
    T.root.classList.toggle('track', !animate);
    const cw = ph ? vw - 24 : Math.min(360, vw - 32);
    T.card.style.width = cw + 'px';
    const ch = cardHeight();
    // re-read the element: the page may have redrawn it since
    const els = T.item && T.item.s.target ? asList(T.item.s.target()).filter(shown) : [];
    const show = T.item.els.length > 0 && els.length > 0;
    let sp;
    if (show) {
      const r = union(els), pad = ph ? 5 : 8;
      const top = Math.max(8, r.top - pad), left = Math.max(8, r.left - pad);
      // A tall section is cut short, unless the card fits above it, so the card always has room.
      const roomAbove = top - 16 - ch >= 12 && !ph;
      const maxH = roomAbove ? vh - top - 8 : Math.max(80, vh - top - ch - (ph ? 24 : 44));
      sp = { top, left, width: Math.min(vw - 8, r.right + pad) - left, height: Math.min(r.bottom + pad - top, maxH, vh - top - 8) };
    } else sp = { top: vh / 2, left: vw / 2, width: 0, height: 0 };
    T.spot.classList.toggle('none', !show);
    Object.assign(T.spot.style, { top: sp.top + 'px', left: sp.left + 'px', width: sp.width + 'px', height: sp.height + 'px' });
    let top, left;
    if (!show) { top = (vh - ch) / 2; left = (vw - cw) / 2; }
    else if (ph) { top = vh - ch - 12; left = 12; }
    else {
      const gap = 16, clampX = x => Math.max(16, Math.min(x, vw - cw - 16));
      if (sp.top + sp.height + gap + ch <= vh - 12) { top = sp.top + sp.height + gap; left = clampX(sp.left); }
      else if (sp.top - gap - ch >= 12) { top = sp.top - gap - ch; left = clampX(sp.left); }
      else if (sp.left + sp.width + gap + cw <= vw - 12) { left = sp.left + sp.width + gap; top = Math.max(12, Math.min(sp.top, vh - ch - 12)); }
      else if (sp.left - gap - cw >= 12) { left = sp.left - gap - cw; top = Math.max(12, Math.min(sp.top, vh - ch - 12)); }
      else { top = vh - ch - 16; left = clampX(sp.left); }
    }
    T.card.style.top = Math.max(8, top) + 'px';
    T.card.style.left = left + 'px';
  }

  function retrack() {
    if (!T || T.settling || T.pending) return;
    T.pending = requestAnimationFrame(() => { if (T) { T.pending = 0; layout(false); } });
  }

  function onKey(e) {
    if (!T || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); end(true); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); move(1); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); move(-1); }
    else if (e.key === 'Tab') {  // the page behind is inert; keep Tab on the card's buttons
      const f = [...T.card.querySelectorAll('button')].filter(b => !b.hidden);
      const i = f.indexOf(document.activeElement);
      e.preventDefault();
      f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
    }
  }

  // ---- when it starts -----------------------------------------------------------------------------------------
  function offer() {
    const header = q('main > header');
    if (!header || q('.tour-offer')) return;
    const box = document.createElement('div'); box.className = 'tour-offer'; box.setAttribute('role', 'status');
    const s = document.createElement('span'); s.textContent = 'New: take a one-minute tour of the ' + NAME[PAGE] + '.';
    const go = document.createElement('button'); go.className = 'go'; go.type = 'button'; go.textContent = 'Take the tour';
    const no = document.createElement('button'); no.type = 'button'; no.textContent = 'No thanks';
    go.onclick = () => { box.remove(); tell(PAGE); start(0); };
    no.onclick = () => { box.remove(); tell(PAGE); };
    box.append(s, go, no);
    header.after(box);
  }

  // After the page has drawn its data, and only while someone is looking at it.
  function whenReady(fn) {
    // Wait until the page has stopped filling in (no change for 400 ms, 5 s at most), so the step count doesn't change under the reader.
    const calm = done => {
      let t, cap; const mo = new MutationObserver(() => { clearTimeout(t); t = setTimeout(fin, 400); });
      const fin = () => { mo.disconnect(); clearTimeout(t); clearTimeout(cap); done(); };
      mo.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
      t = setTimeout(fin, 700); cap = setTimeout(fin, 5000);
    };
    const go = () => calm(() => { if (document.hidden) document.addEventListener('visibilitychange', () => { if (!document.hidden) fn(); }, { once: true }); else fn(); });
    if (document.readyState === 'complete') go(); else addEventListener('load', go, { once: true });
  }

  const btn = document.getElementById('tourOpen');
  if (btn) btn.onclick = () => start(0);

  const m = /^#tour(?:=(last))?$/.exec(location.hash);
  if (m) {
    history.replaceState(null, '', location.pathname + location.search);  // a refresh must not restart it
    whenReady(() => start(m[1] === 'last' ? 'last' : 0, true));
  } else {
    fetch('/api/tour').then(r => r.json()).then(st => {
      if (st[PAGE] === 'auto') whenReady(() => { if (!T && !document.querySelector('dialog[open]')) start(0); });
      else if (st[PAGE] === 'offer') offer();
    }).catch(e => console.error('The tour could not check if you have seen it:', e));
  }
  window.CrateTour = { start: from => start(from || 0) };
})();
