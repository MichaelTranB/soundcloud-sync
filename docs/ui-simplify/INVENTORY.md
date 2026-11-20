# Feature inventory: where everything lives now

Nothing was removed. Every element ID the pages' JavaScript uses is unchanged (checked by diffing the `id="…"` lists against `main`). "Up front" is what a first-time visitor sees; "folded" is one click away under a labelled fold whose closed line already states its status.

## The Crate (`/`, index.html)

| Feature | Before | Now |
|---|---|---|
| Sync Now | one of several red buttons | the one filled red button, top right |
| Library Manager link | milk-white button | quiet outlined button next to it |
| How it works / Take the tour / FAQ / Setup checklist | four buttons of mixed styles in the header | plain text links under the title |
| Status (songs on the Mac, left to find, USB, SoundCloud sign-in) | four big tiles | one calm line |
| Add a playlist (+ Liked Songs, "find yours on SoundCloud", assistant helper, Liked Songs options) | up front | up front (card 1 of 2) |
| USB drive: pick, Copy Now, eject switch, ask-first "Go ahead / Not now" | up front | up front (card 2 of 2) |
| USB to SoundCloud (Make playlists) | up front | folded under **More** |
| Soulseek sign-in / Change | up front | folded under **More** |
| Daily sync time, Auto sync | up front | folded under **More** (closed line shows all three statuses) |
| On your Mac list, search, "Wrong or bad file", Open in rekordbox, Throw them all back, "Length differs" check | up front | unchanged |
| Getting now / Free links / Waiting / Not found, shop links (Bandcamp, Beatport, Traxsource, Juno, Qobuz), Claude/Codex helpers | up front | unchanged |
| Slot for new review lists ("Maybe the wrong file", "Names to tidy") | n/a | empty `#checkNew` after the Mac list, for the other chat's include |

## Library Manager (`/dj`, dj.html)

| Feature | Before | Now |
|---|---|---|
| Update decks now | one of six similar ghost buttons | the one filled red button, top right |
| Back to The Crate | milk-white button | quiet outlined button |
| How it works / Take the tour / FAQ / Options | four ghost buttons | plain text links under the title |
| Counts and decks status | four big tiles | one calm line |
| Set-up card (AcoustID key), "Go ahead" USB ask | up front | unchanged (only shown when needed) |
| Your decks (Engine DJ, rekordbox Mac and USB, Serato, Cues + Undo, Song recognition + switch) | up front | up front |
| USB folders (One folder / EDM+Other / By genre, Use this, All songs switch, Change place, + Another folder) | up front | folded under **USB folders, checks & backup** |
| Copy from another USB (pick songs, Copy songs, Copy to my library) | up front | same fold |
| Club check | up front | same fold |
| Backup (Back up now, Repair this USB, Put it back) | up front | same fold |
| Genres: pills, to-do pills, + Add genre, Remove genres | up front | unchanged |
| Songs: search, sort, select all, Convert to AIFF, Add cover & details, Put on USB, Fix names, per-song Edit / genre picker / Fix / It's fine / Use this / Undo / Add to playlist / ▶ player with waveform, Open in rekordbox, Show in Finder | up front | unchanged |
| Options dialog (every switch, Change links) | button | text link; "Change" links open the fold they point into before scrolling |

## Tours (`tour.js`)

Home tour reordered to the new first-time path (paste a playlist → pick USB → Sync Now → your tracks, then the folded cards, then hand-off to the Library Manager). Library Manager tour keeps its 12 steps; the USB folders, club check and copy-from-USB steps open the fold themselves. Both tours were stepped through to the last step in the built-in browser.
