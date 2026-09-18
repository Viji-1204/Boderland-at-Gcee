// Checkpoint puzzle (spec section 12) - six built-in types, by checkpoint
// number: scrambled words, picture, rock paper scissors, X/O, riddle,
// crossword. The server deals each team its own version and checks every
// answer and move; the phone only shows the puzzle and sends what was done.
import { api, newIdempotencyKey } from '../../../shared/js/api.js';
import { HEADERS } from '../../../shared/js/copy.js';
import { sound } from '../../../shared/js/sound.js';
import { glyphSVG } from '../../../shared/js/suit-icons.js';
import { esc, toast, vibrate } from '../../../shared/js/ui.js';
import { bindChrome, headerHTML, navHTML } from '../chrome.js';
import { onState, refresh } from '../live.js';
import { pictureURL } from '../puzzle-art.js';

const THROW_ICON = { rock: '✊', paper: '✋', scissors: '✌️' };

export function renderPuzzle(root, navigate) {
  root.innerHTML = `
    ${headerHTML(HEADERS.puzzle)}
    <div class="r2-body" id="puzzle-body"><div class="spinner" style="margin:40px auto;"></div></div>
    ${navHTML('')}
  `;
  bindChrome(root, navigate);
  const body = root.querySelector('#puzzle-body');
  let shownId = null;
  let busy = false;
  const timers = new Set();

  function empty(s) {
    const t = s.team;
    let text = 'No puzzle is open right now.';
    let action = '<button class="cta-btn" id="to-scan" type="button">OPEN THE SCANNER</button>';
    if (t.status === 'ACTIVE') text = 'Solved! Follow the radar to your next checkpoint and scan its QR.';
    if (t.status === 'FINAL') { text = 'Every checkpoint is cleared - go and find the Joker.'; action = '<button class="cta-btn" id="to-radar" type="button">OPEN THE RADAR</button>'; }
    if (t.status === 'FROZEN') text = 'You are frozen - the puzzle waits for you.';
    body.innerHTML = `
      <div class="r2-empty">
        <div class="r2-empty-icon">${glyphSVG('puzzle', { size: 54, stroke: 1.5 })}</div>
        <p>${esc(text)}</p>
      </div>${action}`;
    const toScan = body.querySelector('#to-scan');
    if (toScan) toScan.addEventListener('click', () => navigate('#/scan'));
    const toRadar = body.querySelector('#to-radar');
    if (toRadar) toRadar.addEventListener('click', () => navigate('#/radar'));
    shownId = null;
  }

  function solved(res) {
    sound.puzzleSolved();
    vibrate([80, 40, 80]);
    toast(res.message, { success: true, duration: 4600 });
    refresh().catch(() => {}).finally(() => navigate(res.next === 'FINAL' ? '#/home' : '#/radar'));
  }

  /** Send one move. Returns the reply when the puzzle goes on, else null. */
  async function send(move) {
    if (busy) return null;
    busy = true;
    try {
      const res = await api.team.play(move, newIdempotencyKey('play'));
      if (res.solved) { solved(res); return null; }
      return res;
    } catch (err) {
      if (err.status === 429) return { cooldown: err.body.retry_after_s || 3, message: err.message };
      toast(err.message, { error: true });
      return null;
    } finally {
      busy = false;
    }
  }

  function cooldown(btn, seconds, label) {
    let left = Math.ceil(seconds || 0);
    if (left <= 0) { btn.disabled = false; btn.textContent = label; return; }
    btn.disabled = true;
    btn.textContent = `WAIT ${left}s`;
    const timer = setInterval(() => {
      left -= 1;
      if (left <= 0) { clearInterval(timer); timers.delete(timer); btn.disabled = false; btn.textContent = label; } else btn.textContent = `WAIT ${left}s`;
    }, 1000);
    timers.add(timer);
  }

  // --- 1 scrambled words / 5 riddle: a typed answer ---------------------------
  function textPuzzle(box, p) {
    const d = p.data;
    const prompt = p.kind === 'scramble'
      ? `<div class="r2-tiles ${d.mode}">${d.tiles.map((t) => `<span>${esc(t)}</span>`).join('')}</div>
         <p class="r2-small-note">${d.mode === 'letters' ? `${d.count} letters - one word` : `${d.count} words - put them in the right order`}</p>`
      : `<p class="r2-question">${esc(d.question)}</p>`;
    box.innerHTML = `
      <div class="r2-panel">${prompt}</div>
      <form class="r2-panel" data-form>
        <div class="field" style="margin:0;"><label class="tier-label"><span class="primary">回答</span><span class="secondary">Your answer</span></label>
          <input data-answer type="text" autocomplete="off" autocapitalize="characters" spellcheck="false" required /></div>
        <div class="field-error" data-err style="display:none;"></div>
        <button class="cta-btn" data-submit type="submit" style="margin-top:14px;">SUBMIT ANSWER</button>
      </form>
      ${d.hint ? '<button class="r2-hint-btn" data-hint-btn type="button">Need a hint?</button><div class="r2-hint" data-hint hidden></div>' : ''}
      <p class="r2-small-note">Wrong answers cost nothing - just a short wait before the next try.</p>`;
    const btn = box.querySelector('[data-submit]');
    const err = box.querySelector('[data-err]');
    const hintBtn = box.querySelector('[data-hint-btn]');
    if (hintBtn) hintBtn.addEventListener('click', () => {
      const hint = box.querySelector('[data-hint]');
      hint.textContent = d.hint;
      hint.hidden = false;
      hintBtn.remove();
    });
    if (p.retry_after_s > 0) cooldown(btn, p.retry_after_s, 'SUBMIT ANSWER');
    box.querySelector('[data-form]').addEventListener('submit', async (e) => {
      e.preventDefault();
      const answer = box.querySelector('[data-answer]').value.trim();
      if (!answer) return;
      btn.disabled = true;
      err.style.display = 'none';
      const res = await send({ answer });
      if (!res) { btn.disabled = false; return; }
      sound.error();
      vibrate(160);
      err.textContent = res.message;
      err.style.display = 'block';
      cooldown(btn, res.cooldown || res.retry_after_s, 'SUBMIT ANSWER');
    });
  }

  // --- 2 scrambled picture: tap two tiles to swap ----------------------------------
  function picturePuzzle(box, p) {
    const { side, image } = p.data;
    const start = p.data.order.slice();
    let order = start.slice();
    let swaps = [];
    let picked = null;
    const url = pictureURL(image);
    box.innerHTML = `
      <div class="r2-panel">
        <div class="r2-pic-grid" data-grid style="--pic:url('${url}');--side:${side};"></div>
        <div class="r2-pic-foot">
          <img class="r2-pic-preview" src="${url}" alt="What the finished picture looks like" />
          <div><strong>Make it look like this.</strong><br /><span class="r2-small-note" data-count>0 swaps</span></div>
        </div>
      </div>`;
    const grid = box.querySelector('[data-grid]');
    const count = box.querySelector('[data-count]');
    const step = side > 1 ? 100 / (side - 1) : 0;
    function draw() {
      grid.innerHTML = order.map((tile, pos) => `
        <button type="button" class="r2-pic-tile ${picked === pos ? 'picked' : ''}" data-pos="${pos}" aria-label="Tile ${pos + 1}"
          style="background-position:${(tile % side) * step}% ${Math.floor(tile / side) * step}%;"></button>`).join('');
      count.textContent = `${swaps.length} swap${swaps.length === 1 ? '' : 's'}`;
    }
    grid.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-pos]');
      if (!btn || busy) return;
      const pos = Number(btn.dataset.pos);
      if (picked === null || picked === pos) { picked = picked === pos ? null : pos; draw(); return; }
      [order[picked], order[pos]] = [order[pos], order[picked]];
      swaps.push([picked, pos]);
      picked = null;
      draw();
      if (!order.every((tile, i) => tile === i)) return;
      const res = await send({ swaps });
      if (res) { // shouldn't happen - start again from the dealt shuffle
        toast(res.message, { error: true });
        order = start.slice();
        swaps = [];
        draw();
      }
    });
    draw();
  }

  // --- 3 rock paper scissors against the computer --------------------------------------
  function rpsGame(box, p) {
    let d = p.data;
    function draw(message) {
      const last = d.last;
      box.innerHTML = `
        <div class="r2-panel r2-rps">
          <div class="r2-score">
            <div><span>YOU</span><strong>${d.you}</strong></div>
            <div class="r2-score-vs">first to ${d.target}</div>
            <div><span>COMPUTER</span><strong>${d.cpu}</strong></div>
          </div>
          <div class="r2-rps-last">${last
            ? `<span class="r2-rps-hand">${THROW_ICON[last.you]}</span><span class="r2-small-note">vs</span><span class="r2-rps-hand">${THROW_ICON[last.cpu]}</span>`
            : '<span class="r2-small-note">Make your first throw</span>'}</div>
          <p class="r2-rps-msg">${esc(message || (last ? '' : 'Win 2 rounds before the computer does.'))}</p>
          <div class="r2-rps-buttons">${Object.entries(THROW_ICON).map(([m, icon]) => `
            <button type="button" class="r2-rps-btn" data-move="${m}"><span>${icon}</span>${m}</button>`).join('')}</div>
          ${d.matches_lost ? `<p class="r2-small-note">Matches lost so far: ${d.matches_lost}</p>` : ''}
        </div>`;
      box.querySelectorAll('[data-move]').forEach((b) => b.addEventListener('click', async () => {
        box.querySelectorAll('[data-move]').forEach((x) => { x.disabled = true; });
        const res = await send({ move: b.dataset.move });
        if (!res) { box.querySelectorAll('[data-move]').forEach((x) => { x.disabled = false; }); return; }
        d = res.puzzle.data;
        if (d.last && d.last.result === 'lose') vibrate(120);
        draw(res.message);
      }));
    }
    draw();
  }

  // --- 4 X/O against the computer ------------------------------------------------------
  function xoGame(box, p) {
    let d = p.data;
    function draw(message, finishedBoard) {
      const board = finishedBoard || d.board;
      box.innerHTML = `
        <div class="r2-panel r2-xo">
          <p class="r2-xo-msg">${esc(message || 'You are X and go first. Win once to pass.')}</p>
          <div class="r2-xo-board">${[...board].map((ch, i) => `
            <button type="button" class="r2-xo-cell ${ch === 'X' ? 'x' : ch === 'O' ? 'o' : ''}" data-cell="${i}"
              ${ch !== '.' || finishedBoard ? 'disabled' : ''} aria-label="Square ${i + 1}">${ch === '.' ? '' : ch}</button>`).join('')}</div>
          ${d.games ? `<p class="r2-small-note">Games played: ${d.games}</p>` : ''}
        </div>`;
      box.querySelectorAll('[data-cell]:not([disabled])').forEach((cell) => cell.addEventListener('click', async () => {
        const i = Number(cell.dataset.cell);
        cell.textContent = 'X';
        cell.classList.add('x');
        box.querySelectorAll('[data-cell]').forEach((x) => { x.disabled = true; });
        const res = await send({ move: i });
        if (!res) { draw(); return; }
        d = res.puzzle.data;
        const ended = d.last && d.board === '.........';
        if (!ended) { draw(res.message); return; }
        vibrate(120);
        draw(res.message, d.last.board); // show how it ended, then a fresh board
        const timer = setTimeout(() => { timers.delete(timer); draw('New game - you are X, go first.'); }, 1800);
        timers.add(timer);
      }));
    }
    draw();
  }

  // --- 6 crossword -------------------------------------------------------------------------
  function crosswordPuzzle(box, p) {
    const d = p.data;
    const saveKey = `bl2_cw_${p.id}`;
    let saved = {};
    try { saved = JSON.parse(sessionStorage.getItem(saveKey) || '{}'); } catch (_) { saved = {}; }
    const clues = (title, list) => `<div><h4>${title}</h4>${list.map((e) => `<p><strong>${e.n}</strong> ${esc(e.clue)} <span class="r2-small-note">(${e.len})</span></p>`).join('')}</div>`;
    box.innerHTML = `
      <div class="r2-panel">
        <div class="r2-cw" style="--cols:${d.cols};">${d.cells.map((row, r) => row.map((cell, c) => (cell === null
          ? '<div class="r2-cw-block"></div>'
          : `<label class="r2-cw-cell">${cell ? `<span class="r2-cw-n">${cell}</span>` : ''}<input data-r="${r}" data-c="${c}" maxlength="1"
               autocomplete="off" autocapitalize="characters" spellcheck="false" value="${esc(saved[`${r},${c}`] || '')}" aria-label="Row ${r + 1}, column ${c + 1}" /></label>`)).join('')).join('')}</div>
      </div>
      <div class="r2-panel r2-cw-clues">${clues('Across', d.across)}${clues('Down', d.down)}</div>
      <div class="field-error" data-err style="display:none;"></div>
      <button class="cta-btn" data-check type="button">CHECK CROSSWORD</button>`;
    const cell = (r, c) => box.querySelector(`input[data-r="${r}"][data-c="${c}"]`);
    let across = true; // typing direction, picked from the neighbours of the first cell typed in
    box.querySelectorAll('.r2-cw input').forEach((input) => {
      const r = Number(input.dataset.r);
      const c = Number(input.dataset.c);
      input.addEventListener('focus', () => {
        if (!cell(r, c + 1) && !cell(r, c - 1)) across = false;
        else if (!cell(r + 1, c) && !cell(r - 1, c)) across = true;
      });
      input.addEventListener('input', () => {
        input.value = input.value.replace(/[^a-z]/gi, '').slice(-1).toUpperCase();
        saved[`${r},${c}`] = input.value;
        try { sessionStorage.setItem(saveKey, JSON.stringify(saved)); } catch (_) { /* private mode */ }
        if (input.value) (across ? cell(r, c + 1) || cell(r + 1, c) : cell(r + 1, c) || cell(r, c + 1))?.focus();
      });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' && !input.value) (across ? cell(r, c - 1) : cell(r - 1, c))?.focus();
      });
    });
    const check = box.querySelector('[data-check]');
    const err = box.querySelector('[data-err]');
    if (p.retry_after_s > 0) cooldown(check, p.retry_after_s, 'CHECK CROSSWORD');
    check.addEventListener('click', async () => {
      const grid = d.cells.map((row, r) => row.map((c, ci) => (c === null ? ' ' : (cell(r, ci).value || ' '))).join(''));
      check.disabled = true;
      err.style.display = 'none';
      const res = await send({ grid });
      if (!res) { check.disabled = false; return; }
      sound.error();
      err.textContent = res.message;
      err.style.display = 'block';
      cooldown(check, res.cooldown || res.retry_after_s, 'CHECK CROSSWORD');
    });
  }

  const RENDER = { scramble: textPuzzle, riddle: textPuzzle, picture: picturePuzzle, rps: rpsGame, tictactoe: xoGame, crossword: crosswordPuzzle };

  function show(p) {
    shownId = p.id;
    body.innerHTML = `
      <div class="r2-panel">
        <div class="r2-row">
          <span class="r2-eyebrow">Checkpoint ${p.checkpoint} of ${p.total}</span>
          <span class="r2-kind">${esc(p.label)}</span>
        </div>
        <p class="r2-instructions">${esc(p.instructions)}</p>
      </div>
      <div class="r2-puzzle-box" data-box></div>`;
    (RENDER[p.kind] || textPuzzle)(body.querySelector('[data-box]'), p);
  }

  // Games change with every move, so always start from the server's latest
  // version rather than a cached copy.
  async function openFresh() {
    try {
      const { puzzle } = await api.team.currentPuzzle();
      if (puzzle) show(puzzle);
    } catch (err) {
      body.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`;
    }
  }

  const unsubscribe = onState((s) => {
    if (s.puzzle && s.team.status === 'PUZZLE_LOCKED') {
      if (s.puzzle.id !== shownId) { shownId = s.puzzle.id; openFresh(); }
    } else if (s.team.status !== 'FROZEN' || !shownId) {
      empty(s);
    }
  });
  refresh().catch((err) => { body.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`; });
  return () => { unsubscribe(); timers.forEach((t) => { clearInterval(t); clearTimeout(t); }); };
}
