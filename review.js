// Check new downloads (review.py, app.py's /api/review), on the main page in #checkNew.
// Two lists, kept apart because they ask different things of you:
//   Maybe the wrong song: what's inside the file names another song or artist than the playlist's. Listen, open it in
//     rekordbox or Finder, then "It's the right song" or "Throw away" (to the Trash; another copy is looked for).
//     These are never in "Tidy all": a wrong file with a right name would only hide it.
//   Names to tidy: the right song, named a little differently from its playlist ("Artist - Title" in the title, "&"
//     for ","). "Tidy" or "Tidy all" gives each exactly the playlist's title and artist (and a Soulseek file its file
//     name); "Undo" puts any back.
// Uses the page's el(), call(), listen(), player and playing.
(() => {
  const box = document.getElementById('checkNew');
  if (!box) return;
  let data = null, open = false, all = false, timer = 0;
  document.head.append(el('style', { textContent: '#checkNew details.fold { margin: 0 0 28px; } #checkNew .review { padding: 6px 4px 0; }' +
    ' #checkNew .review h2 { margin-top: 26px; align-items: center; } #checkNew .review h2 button { padding: 8px 16px; font-size: 14px; }' +
    ' #checkNew li .n b { font-weight: 600; } #checkNew .review > details { margin-top: 22px; }' }));
  const said = (a, t) => (a || t) ? `${a || 'no artist'} — ${t || 'no title'}` : 'no name inside the file';

  async function load() {
    try {
      const r = await fetch('/api/review');
      data = await r.json();
    } catch (e) { return; }
    draw();
    clearTimeout(timer);
    if (data.busy) timer = setTimeout(load, 3000);
  }
  async function act(body, btn) {
    if (btn) { btn.disabled = true; btn.setAttribute('aria-busy', 'true'); }
    try {
      const r = await fetch('/api/review', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Something went wrong.');
      data = j; draw();
      if (j.busy) { clearTimeout(timer); timer = setTimeout(load, 3000); }
    } catch (e) {
      alert(e.message);
      if (btn) { btn.disabled = false; btn.removeAttribute('aria-busy'); }
    }
  }

  const play = t => el('button', {
    className: 'play' + (playing === t.file ? ' on' : ''), textContent: playing === t.file ? '❚❚' : '▶',
    title: playing === t.file ? 'Stop' : 'Listen', ariaLabel: (playing === t.file ? 'Stop ' : 'Listen to ') + t.name,
    onclick: () => listen(t.file) });
  const song = t => t.link
    ? el('a', { className: 'song', href: t.link, target: '_blank', rel: 'noopener', title: 'The song in its playlist' }, said(t.want.artist, t.want.title))
    : said(t.want.artist, t.want.title);

  function wrongRow(t) {
    return el('li', {}, play(t),
      el('span', { className: 'n' }, song(t),
        el('small', { textContent: `The file says: ${said(t.artist, t.title)}` }),
        el('small', { textContent: t.why.charAt(0).toUpperCase() + t.why.slice(1) + '.' })),
      el('button', { className: 'ghost', textContent: 'Open in rekordbox', title: 'Opens this file in rekordbox on your Mac',
        onclick: () => call('/api/dj/rekordbox', { file: t.file }).then(() => {}, e => alert(e.message)) }),
      el('button', { className: 'ghost', textContent: "It's the right song",
        title: "Keeps it. It isn't asked about again unless the file changes; its name then goes to Names to tidy.",
        onclick: e => act({ keep: t.file }, e.currentTarget) }),
      el('button', { className: 'bad', textContent: 'Show in Finder', onclick: () => call('/api/dj/show', { file: t.file }).catch(e => alert(e.message)) }),
      el('button', { className: 'bad', textContent: 'Throw away', title: 'To the Trash, never taken again, and another copy is looked for right away',
        onclick: async e => {
          if (!confirm(`Throw away "${t.name}"?\n\nIt goes to the Trash, this file is never taken again, and The Crate starts looking for another copy of "${said(t.want.artist, t.want.title)}" right away.`)) return;
          const b = e.currentTarget; b.disabled = true;
          try { await call('/api/soulseek-bad', { file: t.file }); load(); } catch (err) { alert(err.message); b.disabled = false; }
        } }));
  }

  function tidyRow(t) {
    return el('li', {}, play(t),
      el('span', { className: 'n' }, el('b', { textContent: said(t.want.artist, t.want.title) }),
        el('small', { textContent: `Now: ${said(t.artist, t.title)}` }),
        ...(t.rename ? [el('small', { textContent: `File name becomes: ${t.to}` })] : [])),
      el('button', { className: 'ghost', textContent: 'Tidy', disabled: !!data.busy, ariaLabel: 'Tidy the name of ' + t.name,
        onclick: e => act({ tidy: [t.file] }, e.currentTarget) }),
      el('button', { className: 'bad', textContent: 'Keep this name', title: "Leaves it as it is. It isn't suggested again unless the name changes.",
        onclick: e => act({ asis: t.file }, e.currentTarget) }));
  }

  function doneRow(t) {
    return el('li', {},
      el('span', { className: 'n' }, said(t.artist, t.title),
        el('small', { textContent: (t.said && t.said.length ? `Was: ${said(t.said[0], t.said[1])}` : `Was: ${t.was}`) +
          (t.waiting ? ' · its file name changes at the next sync.' : '') })),
      el('button', { className: 'bad', textContent: 'Undo', title: 'Puts back the name it had before',
        onclick: e => act({ undo: t.file }, e.currentTarget) }));
  }

  function draw() {
    const d = data; if (!d) return;
    const w = d.wrong || [], t = d.tidy || [], done = d.done || [];
    if (!w.length && !t.length && !done.length && !d.error) { box.replaceChildren(); return; }
    const parts = [];
    if (w.length) parts.push(el('b', { style: 'color:var(--warn)', textContent: `${w.length} may be the wrong song` }));
    if (t.length) parts.push(`${t.length} name${t.length === 1 ? '' : 's'} to tidy`);
    if (!w.length && !t.length) parts.push('All checked');
    const sum = el('summary', {}, el('b', { textContent: 'Check new downloads' }),
      el('span', {}, ...parts.flatMap((p, i) => i ? [' · ', p] : [p])));
    const body = [];
    if (d.error) body.push(el('div', { className: 'note bad', textContent: d.error }));
    if (w.length) body.push(
      el('h2', {}, el('span', {}, 'Maybe the wrong song ', el('em', { textContent: w.length }))),
      el('div', { className: 'note', textContent: "What's inside these files names another song or artist than the playlist. Listen first: keep it, or throw it away and another copy is looked for." }),
      el('ul', {}, ...w.map(wrongRow)));
    if (t.length) {
      const shown = all ? t : t.slice(0, 15);
      body.push(
        el('h2', {}, el('span', {}, 'Names to tidy ', el('em', { textContent: t.length })),
          el('button', { textContent: d.busy ? 'Tidying…' : 'Tidy all', disabled: !!d.busy,
            title: 'Every song below gets exactly the title and artist its playlist shows. Undo puts any back.',
            onclick: e => { if (confirm(`Give all ${t.length} songs the name their playlist shows?\n\nOnly the names change, never the sound. Undo puts any back.`)) act({ tidy: 'all' }, e.currentTarget); } })),
        el('div', { className: 'note', textContent: d.busy ? 'Tidying the names now. They change one by one.'
          : 'The right songs, named a little differently from their playlist. Tidy gives each exactly the playlist\'s title and artist, so rekordbox shows clean titles.' }),
        el('ul', {}, ...shown.map(tidyRow)),
        ...(t.length > shown.length ? [el('button', { className: 'ghost', style: 'margin-top:12px', textContent: `Show all ${t.length}`, onclick: () => { all = true; draw(); } })] : []));
    }
    if (done.length) body.push(el('details', {}, el('summary', { textContent: `Tidied (${done.length})` }), el('ul', {}, ...done.map(doneRow))));
    const fold = el('details', { className: 'fold', open: open }, sum, el('div', { className: 'review' }, ...body));
    fold.addEventListener('toggle', () => { open = fold.open; });
    box.replaceChildren(fold);
  }

  for (const ev of ['play', 'pause', 'ended']) player.addEventListener(ev, () => { if (data) draw(); });
  load();
  setInterval(() => { if (document.visibilityState === 'visible' && !(data && data.busy)) load(); }, 60000);
})();
