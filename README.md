# Borderland @ GCEE — Round 2 (GPS treasure hunt)

Round 2 of the Alice-in-Borderland event. Teams walk the campus on their phones:
**scan the checkpoint QR → solve its puzzle → follow the radar to the next one →
collect the Jack, Queen and King → find the Joker at the coordinators' bench.**
Powers add some chaos: a Guide to your next checkpoint, three attacks (Freeze, Jam,
Trap) and three defences (Shield, Reflect, Ward). Coordinators run everything live
from an admin console.

Built to the spec in `Round 2 Full Architecture/…/ROUND_2_FINAL_SPEC_AND_ARCHITECTURE.md`,
on top of Round 1:

- **Same look & feel as Round 1.** Round 1's `theme.css`, `team.css` and `admin.css`
  are reused unchanged. The phone app is Round 1's shell: login screen, dark "phone"
  home hub, diamond bottom nav, 【bracket】 headers. Round 1's camera button, locked
  in Round 1, now opens the QR scanner.
- **Same login system as Round 1.** Teams log in with a team code (`B@GCEE-1234#`)
  and a password (the first 4 digits of the leader's phone). Admins log in with
  username + password (bcrypt + JWT). Teams are created by the same spreadsheet
  import. Import Round 1's **"Round 2 Qualifiers" export** and qualified teams keep
  their Round 1 login.

---

## 1. Run it on localhost (Windows PowerShell)

There are two ways to run it. Both serve **http://localhost:8000**, so run only one at a time.

| | A. Python (quickest) | B. Docker Desktop |
|---|---|---|
| Database | SQLite file `backend/data/round2.db` | Postgres, in the `pgdata` Docker volume |
| Shows in Docker Desktop? | No, it runs in your terminal | Yes, as **borderland-round2** |
| Admin login | `admin` / `admin123` | `admin` / the `ADMIN_PASSWORD` in `.env` |

### A. Python

Needs Python 3.11+ (tested on 3.12).

```powershell
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

On the very first start it creates the database (`backend/data/round2.db`), the
admin account and a **ready-to-play demo event** with 6 teams. The server runs until
you press `Ctrl+C` or close that terminal. Your data stays between restarts.

### B. Docker Desktop (Postgres, like a real server)

1. Start Docker Desktop.
2. `.env` must exist next to `docker-compose.yml`. A local one with random secrets
   was generated for testing. Otherwise copy `.env.example` to `.env` and fill it in.
3. In the project folder (the one containing `docker-compose.yml`), run:

   ```powershell
   docker compose up -d --build
   ```

It appears in Docker Desktop → **Containers** as **borderland-round2** (`api` +
`postgres`). With `SEED_DEMO=true` in `.env`, the first start creates the same demo
event. Everyday commands:

| Command | What it does |
|---|---|
| `docker compose ps` | status: `api` should say **(healthy)** |
| `docker compose logs -f api` | live server log (`Ctrl+C` stops watching, not the server) |
| `docker compose stop` / `start` | stop / start again, data kept (same as Docker Desktop's buttons) |
| `docker compose up -d --build` | apply code changes |
| `docker compose down -v` | **deletes the Docker database** for a fresh start |

The **borderland-gcee-main** stack in Docker Desktop is the old **Round 1** setup
from another folder. It also uses port 8000, so don't run both at once.

### Is it running?

Open these URLs (the same for A and B):

| What | URL |
|---|---|
| Health check | http://localhost:8000/api/v1/health → `{"status":"ok","database":"sqlite"}` (`"postgresql"` in Docker) |
| Team phone app | http://localhost:8000/team-app/ |
| Coordinator console | http://localhost:8000/admin-app/ |
| API docs | http://localhost:8000/api/docs |

- **Python:** the terminal shows `Round 2 ready - database: …` and `Uvicorn running on http://127.0.0.1:8000`.
- **Docker:** both containers are green in Docker Desktop, and `docker compose ps` shows `(healthy)`.
- **Page won't load?** Nothing is running: the terminal was closed, or the stack is stopped.
- **"Address already in use" / "port is already allocated"?** Something else has
  port 8000: stop the other option or Round 1's stack, or pick another port
  (`--port 8001`, or `ROUND2_PORT=8001` in `.env`).

### Demo logins

Admin: **`admin` / `admin123`** (Python) or `admin` / the `ADMIN_PASSWORD` in `.env`
(Docker). Change it before a real event (see section 5).

| Team | Team code | Password |
|---|---|---|
| Dragon Warriors | `B@GCEE-1001#` | `9840` |
| Border Runners | `B@GCEE-1002#` | `9841` |
| Joker's Wild | `B@GCEE-1003#` | `9842` |
| Queen's Gambit | `B@GCEE-1004#` | `9843` |
| Heart Breakers | `B@GCEE-1005#` | `9844` |
| Spade Squad | `B@GCEE-1006#` | `9845` |

Puzzles are built in, so there are no fixed demo answers: each team gets its own
words, riddle, crossword and picture shuffle (see *Puzzles* below).

---

## 2. Check the new features (15-minute walkthrough)

Use a normal browser window for the admin and an **Incognito window** (or a second
browser) for a team, so each keeps its own login. For a phone-sized view, open
Chrome DevTools (`F12`) → device toolbar (`Ctrl+Shift+M`).

1. **Admin → Live Dashboard.** "Ready to lock?" should be all green. Click **Lock
   configuration**, then **START ROUND 2**. Each team card now shows its current
   target, e.g. `Target: #1 L02 · Clock Tower`.
2. **Team → log in** as `B@GCEE-1001#` / `9840`. The home hub shows the status
   strip and apps. With the game not started yet, open **Powers** to buy something.
   When the admin starts the game, the phone updates by itself ("ROUND 2 HAS STARTED!").
3. **Scan.** A laptop has no camera pointed at a sticker, so open **Scanner** →
   *Can't scan? Type the code*, and enter a token from **Admin → QR Codes**.
   - A token for someone else's checkpoint gives **THIS IS NOT YOUR QR · FOUL +1**.
   - Your target (from the dashboard card) gives **CHECKPOINT 1 / 8 VERIFIED**, a
     sentence fragment and **Solve the puzzle**.
4. **Puzzle.** The checkpoint's built-in puzzle opens: scrambled words, a picture
   puzzle, rock paper scissors, X/O, a riddle or a crossword, depending on its
   number. A wrong answer shows "Not quite", no penalty, and a short wait. Solving
   it unlocks the **radar**.
5. **Radar on a laptop.** DevTools → `⋮` → *More tools* → **Sensors** → *Location*:
   enter a custom latitude/longitude (checkpoint coordinates are in **Admin → Setup
   Routes**). The needle, distance and "GOAL IS NEAR" follow your fake position.
6. **Attack.** In a third window, log in as another team → **Powers → Freeze**
   (or Jam / Trap) → pick Dragon Warriors. Dragon Warriors' phone shows
   **INCOMING FREEZE** with a 15 s countdown. Shield it, Reflect it back, accept it,
   or let it run out; the server freezes the
   team automatically (full-screen **FROZEN** timer). Admin can **Unfreeze**.
7. **Coordinator overrides** on each team card: +/− foul, freeze/unfreeze, unlock
   puzzle, disqualify/reinstate. Everything lands in **Logs**, with the automatic
   game log and the manual coordinator log kept separate.
8. **Finish.** Clear all 8 checkpoints. The phone switches to
   **Find the Joker** and the radar points to the coordinators' bench. Admin clicks
   **🃏 Verify Joker** and the team sees the celebration.
9. **Results.** Admin → **End game**. Teams see **Results** (rank, name and time,
   never fouls). **Admin → Results** shows the full coordinator view and
   **Export (.xlsx)**.

### Automated checks

```powershell
cd backend
python -m pytest              # 103 tests: rules, the six puzzles, powers, privacy, lifecycle, import, auth, WebSockets, migrations, photos, health
python full_verification.py   # plays a whole event through the real API and prints each step
```

Both use a temporary database, so your data is never touched. (The old scripts in
`backend/` wiped `round2.db`; they have been replaced.)

The same tests on **Postgres**, using a throwaway container (needs Docker):

```powershell
docker run -d --rm --name bl2-pg-test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=round2_test -p 127.0.0.1:55432:5432 postgres:16
# wait ~5 seconds for it to start, then:
$env:TEST_DATABASE_URL = "postgresql+psycopg2://postgres:test@127.0.0.1:55432/round2_test"
python -m pytest
Remove-Item Env:TEST_DATABASE_URL; docker stop bl2-pg-test   # the container deletes itself
```

---

## 3. Test on real phones (same Wi-Fi)

Phone browsers only allow the **camera** (QR scanner) and **GPS** (radar) on
`https://` addresses. `http://<laptop-ip>:8000` opens on a phone, but it can't scan.
Keep the server running (Docker or Python), then in a second terminal run:

```powershell
cd backend
python dev_https.py
```

It adds HTTPS in front of the server on port 8000 (same data; if nothing is running
there, it starts a server itself). It prints the address, e.g.
`https://10.186.139.188:8443/team-app/`. Leave that window open.

1. **Laptop:** open the printed **Admin app** address. The browser warns about the
   certificate once: *Advanced → Proceed*. Log in and go to **QR Codes**.
2. **Phone** (same Wi-Fi): point the normal camera at the **"Phones: scan this to
   open the team app"** QR at the top of that page. Accept the warning once:
   - Android (Chrome): *Advanced → Proceed to …*
   - iPhone (Safari): *Show Details → visit this website → Visit Website*
3. Log in. In **Scanner**, tap **Allow** for the camera; in **Radar**, **Allow** location.
4. Scan the checkpoint QRs shown on the laptop (or printed). Each QR is a link, so
   the phone's normal camera works too; one tap on *Yes, scan it* submits it. Links
   never auto-submit, so a rival can't cost you a foul by sending you one.

**Phone can't open the address?** Check it's on the same Wi-Fi as the laptop.
College and guest Wi-Fi often block traffic between devices; if so, connect the
laptop to a phone's hotspot instead. Allow Python through the Windows firewall if
asked. The address changes whenever the laptop joins another network: re-run
`dev_https.py` and use the new address.

**No warnings, any network (even mobile data):** a tunnel gives a real HTTPS
address, e.g. `cloudflared tunnel --url http://localhost:8000`. That's also an
option for event day.

---

## 4. How it's built

```
backend/                 FastAPI + SQLAlchemy 2 (SQLite by default, Postgres via DATABASE_URL)
  app/api/               REST routers (team: auth, me/state, scan, puzzle, radar, powers, leaderboard;
                         admin: events & lifecycle, setup, routes, teams & import, live controls, results)
  app/services/          all game rules: scan_service (scan→puzzle→radar), power_service, route_service,
                         event_service (lifecycle + readiness), state_service, results_service,
                         team_import_service (Round 1 importer), sweeper (attack timeouts)
  app/websockets/        authenticated WebSockets (/ws/team, /ws/admin)
  alembic/               database migrations (schema changes go here - nothing is ever dropped)
  tests/                 pytest suite
frontend/
  shared/                Round 1 theme.css, images, api.js / ws.js / ui.js / copy.js / suit-icons.js
  team-app/              phone app (Round 1 shell + round2.css), installable as a PWA
  admin-app/             coordinator console (Round 1 admin.css + round2-admin.css)
```

Key rules, all enforced on the server (spec sections 10–21, 29):

- **Puzzles are built in and checked by the server.** The phone only sends
  answers and moves. It never receives an answer. The computer's hand in rock
  paper scissors is only thrown after the team's, and the picture puzzle's swaps
  are replayed on the server, so "solved" can't be faked.
- **Wrong QR = foul.** Repeat scans, unknown codes (posters!), and scans while a
  puzzle is open never cost a foul.
- **Frozen, paused, ended, disqualified or not-yet-started teams can't act.**
  Staggered starts apply when teams share a starting checkpoint.
- **The app sends teams to their start.** From the moment the game is live until a
  team scans checkpoint 1, its home screen shows the starting checkpoint by name,
  the live distance from the phone's GPS, and an *Open in Google Maps* walking
  route; the radar shows the same. Every later checkpoint stays radar-only.
- **Routes:** every team visits every selected checkpoint once, in a unique order.
  Each team is dealt its own Jack, Queen and King - three of its stops, picked at
  random when routes are generated, met in that order - so teams find them at
  different checkpoints. The generator also spreads teams out.
- **Privacy:** the radar returns only a rounded distance and bearing, never the
  target's name or coordinates. The public leaderboard and results never show fouls.
  Attackers stay anonymous to their target.
- **Powers.** *Guide* (help) reveals the current target for a few minutes: name,
  exact distance and bearing, and a Google Maps walking route - no coordinator
  needed. Attacks give the rival a response window: *Freeze* stops them, *Jam*
  blacks out their radar (they can still scan), *Trap* plants a foul. Defences:
  *Shield* blocks one attack, *Reflect* blocks it and bounces the effect onto the
  attacker, *Ward* is raised in advance and auto-blocks everything while it lasts.
  Prices, limits and durations are per event (Admin → Event Setup).
- **Real-time:** WebSockets push attacks, freezes and state changes. Every phone
  re-syncs `GET /me/state` on reconnect. All countdowns run on server time.
- **Retries are safe.** Every action carries an idempotency key, so a flaky
  connection can't double-scan or double-attack.
- **Login protection:** team passwords are only 4 digits, so failures are throttled
  per device and per team code (a spoofed address doesn't reset it). Unknown codes
  take as long to reject as wrong passwords, and changing a password logs out
  old sessions.

---

## 5. Getting ready for the real event

1. **Secrets.** Python: create `backend/.env` (see `backend/.env.example`). Docker:
   edit the `.env` next to `docker-compose.yml`. Use a random `JWT_SECRET` and a
   strong `ADMIN_PASSWORD`, and set `ENVIRONMENT=production`.
   Production refuses to start with placeholder secrets. In development, a random
   signing key is generated in `backend/data/.jwt-secret` automatically.
2. **Event.** Admin → Events → *New event*. *Copy setup from* the demo reuses its
   structure and generates fresh QR codes.
3. **Checkpoints.** Admin → **Setup Routes**, on a phone at the `https://` address
   (section 3). Walk the campus; at each spot tap **+**. It fills in the GPS point
   (wait for a green "±… m - good"), takes an optional photo, and **Add** saves it.
   The list shows every checkpoint with its map link and photo: **Edit** (name,
   GPS, radius, in the game or spare, photo) or **Delete**. Up to 15 checkpoints,
   7–9 in the game. (The Jack, Queen and King aren't set here - see Routes below.)
   Adding and deleting need a DRAFT event; names, GPS points and photos can be
   fixed until the event ends. Photos are admin-only and stored in the database.
   Set the final (Joker) destination in **Event Setup**.
4. **Puzzles: nothing to do, they're built in.** Each checkpoint's puzzle follows
   its number and repeats every six (Admin → Puzzles shows the plan):

   | Checkpoints | Puzzle | How it works |
   |---|---|---|
   | L01, L07 | Scrambled words | Letters (or a sentence's words) to put back in order |
   | L02, L08 | Picture puzzle | Tap two tiles to swap them until the card picture is whole |
   | L03, L09 | Rock paper scissors | Beat the computer, first to 2 wins; a lost match starts again |
   | L04, L10 | X/O game | Win one game against the computer (a draw doesn't count) |
   | L05, L11 | Riddle | Type the answer; a hint is one tap away |
   | L06, L12 | Crossword | Small crossword from clues; *Check* names any wrong word |

   Every team gets its own words, riddle, crossword and shuffle, and never the
   same one twice, so answers can't be passed along. The computer in X/O always
   takes a win and usually blocks, but not always, so careful play wins. A team
   that's stuck can be let through with **Unlock puzzle** on its dashboard card.
   To change the words, riddles or crosswords, edit the lists in
   `backend/app/services/puzzles/`; tests check every one.
5. **Teams.** Admin → Teams → *Import from Sheet*. Upload Round 1's "Round 2
   Qualifiers" export or any registration sheet, review, confirm, and download the
   login sheet. Give each team a secret sentence (a *Sentence* column in the
   sheet, or edit per team).
6. **Routes.** Admin → Routes → *Generate*. This also deals every team its own
   Jack, Queen and King on three random checkpoints of its route (J/Q/K in the
   table); *Edit* on a row moves a team's route or its cards by hand.
7. **QR codes.** Admin → QR Codes → Print, from the **public address teams will
   use**, since the codes link there. Stick each one at its checkpoint.
8. **Dry run** with volunteers the day before. Then Dashboard → **Lock** → **Start**.
   After the dry run (or a false start) press **Restart game** on the dashboard: it
   wipes the run - progress, fouls, scans, puzzles, timers, power uses - and goes back
   to CONFIGURED with routes, sentences and prices intact, ready to Start again.
   Tick *Refund all power purchases* if teams should shop again from scratch.

### Hosting

- **Simplest:** one laptop or server running `uvicorn` behind HTTPS. SQLite handles
  one event comfortably, and backing up is copying `backend/data/round2.db`.
- **Docker + Postgres** (spec section 30): as in section 1B, but with strong
  passwords, `ENVIRONMENT=production` and `SEED_DEMO=false` in `.env`. Put an HTTPS
  proxy in front, e.g. [Caddy](https://caddyserver.com):
  `your-domain { reverse_proxy localhost:8000 }`.
- Run **one** API process. The live hub and per-team locks live in memory; see next steps.
- Behind a proxy on another machine or container, set `FORWARDED_ALLOW_IPS` to that
  proxy's address, never `*`, so clients can't fake their IP.

### Reset / housekeeping

- **Fresh start (Python):** stop the server and delete `backend/data/round2.db`. The
  next start creates a new one, with the demo event unless `SEED_DEMO=false`.
- **Fresh start (Docker):** `docker compose down -v`, then `docker compose up -d`.
  The demo event is created only if `.env` has `SEED_DEMO=true`.
- **Schema change:** edit `app/models/models.py`, then run
  `alembic revision --autogenerate -m "what changed"` and restart. Migrations apply
  automatically.

---

## 6. Next steps (suggested order)

1. **Real content:** campus GPS points, puzzles, sentences, final Joker spot; run a
   dry run on the actual phones and network of the venue.
2. **HTTPS hosting** for event day (domain + Caddy, or a tunnel) and printed QR codes
   pointing at it.
3. **Rehearse on the event server:** all 103 tests and the full-event smoke run
   also pass on Postgres 16 (see *Automated checks*), and the Docker stack runs.
   Still run a dry run on the real server and network.
4. **Scale-out (only if needed):** several API processes would need Redis for the
   WebSocket fan-out, locks and rate limits (spec section 25). One process is fine
   for a college event.
5. Nice-to-haves: map picker for checkpoints, a projector "live leaderboard" screen,
   push notifications, and offline caching of the app shell (service worker).

---

## 7. Housekeeping notes

- `round2_backup_before_rebuild_2026-09-18.zip` holds the previous Round 2 code and
  its two old databases. Delete it once you're happy with the new version.
- `backend/test_api.py` and `backend/test_final_qr.py` are now empty pointers to
  `backend/tests/` and can be deleted.
- `round2.db` (top level) and `backend/round2.db` are the **old** databases (old schema).
  The app no longer uses them (it uses `backend/data/round2.db`), and copies are in the zip.
  Safe to delete.
- `Borderland-GCEE-main (2)/` is the Round 1 codebase, kept for reference. Heads-up:
  its latest commit left unbalanced parentheses in `sql/round1_schema.sql` (lines
  ~804/830/913/942) and migration `0015`, so a fresh Round 1 install would fail its
  first migration.
