"""The six built-in checkpoint puzzles (app/services/puzzles)."""
from __future__ import annotations

import json
import random

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.database import SessionLocal
from app.models import PuzzleSession
from app.services import puzzles
from app.services.puzzles import crossword, picture, riddle, rps, scramble, tictactoe
from tests.helpers import answer, clear_checkpoint, open_session, play, route_of, scan, seed, set_team, solve_puzzle

API = "/api/v1"
ANSWER_KEYS = {"answer", "answers", "alt_answers", "solution", "word", "words", "grid"}


def test_types_follow_the_checkpoint_number_and_repeat_every_six():
    kinds = [puzzles.kind_for_code(f"L{n:02d}") for n in range(1, 13)]
    assert kinds == ["scramble", "picture", "rps", "tictactoe", "riddle", "crossword"] * 2


def test_each_team_gets_its_own_version_and_never_the_same_one_twice():
    for module in (scramble, picture, riddle, crossword):
        dealt = {puzzles.pick(f"team-{i}", module.KIND, 0, module.SIZE) for i in range(40)}
        assert len(dealt) > 1  # teams don't all get the same one
        for i in range(40):  # a team's 1st and 2nd checkpoint of a type differ
            assert puzzles.pick(f"team-{i}", module.KIND, 0, module.SIZE) != puzzles.pick(f"team-{i}", module.KIND, 1, module.SIZE)


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


@pytest.mark.parametrize("module", puzzles.ORDER, ids=[m.KIND for m in puzzles.ORDER])
def test_what_the_phone_sees_never_contains_the_answer(module):
    rng = random.Random(7)
    for index in range(module.SIZE):
        view = module.view(module.new_state(index, rng))
        assert not ANSWER_KEYS & _keys(view)
        json.dumps(view)
    if module is crossword:
        for index in range(crossword.SIZE):
            cells = crossword.view(crossword.new_state(index, rng))["cells"]
            assert all(c is None or isinstance(c, int) for row in cells for c in row)  # numbers, never letters


def test_scrambles_are_never_dealt_already_solved():
    rng = random.Random(1)
    for index, (answer_text, _clue, _alts) in enumerate(scramble.ITEMS):
        for _ in range(20):
            state = scramble.new_state(index, rng)
            if state["mode"] == "words":
                assert state["tiles"] != answer_text.split() and sorted(state["tiles"]) == sorted(answer_text.split())
            else:
                assert "".join(state["tiles"]) != answer_text and sorted(state["tiles"]) == sorted(answer_text)


def test_typed_answers_ignore_case_spacing_and_punctuation():
    rng = random.Random()
    word = {"item": 0, "mode": "letters", "tiles": list("DLRBNOEADR"), "clue": ""}  # BORDERLAND
    assert scramble.act(word, {"answer": " border land! "}, rng).solved
    assert not scramble.act(word, {"answer": "borderlands"}, rng).solved
    visa = next(i for i, item in enumerate(scramble.ITEMS) if item[0] == "YOUR VISA IS RUNNING OUT")
    sentence = {"item": visa, "mode": "words", "tiles": [], "clue": ""}
    assert scramble.act(sentence, {"answer": "is your  visa running out?"}, rng).solved
    assert riddle.act({"item": 0}, {"answer": "A Keyboard."}, rng).solved
    with pytest.raises(AppError):
        riddle.act({"item": 0}, {"answer": "   "}, rng)


@pytest.mark.parametrize("index", range(crossword.SIZE))
def test_crossword_clues_cover_every_word_and_a_check_names_wrong_ones(index):
    rng = random.Random()
    state = crossword.new_state(index, rng)
    view = crossword.view(state)  # a word without a clue would fail here
    assert len(view["across"]) + len(view["down"]) == len(crossword.CROSSWORDS[index]["clues"])
    solution = crossword.solution(state)[0]
    assert crossword.act(state, solution, rng).solved
    first = crossword.entries(crossword.CROSSWORDS[index]["grid"])[0]
    grid = list(solution["grid"])
    r, c = first["cells"][-1]
    grid[r] = grid[r][:c] + "Z" + grid[r][c + 1:]
    out = crossword.act(state, {"grid": grid}, rng)
    assert not out.solved and out.attempt and f"{first['n']} {first['dir'].title()}" in out.extra["wrong"]
    with pytest.raises(AppError):
        crossword.act(state, {"grid": ["ABC"]}, rng)


def test_picture_is_checked_by_replaying_the_swaps():
    rng = random.Random(3)
    state = picture.new_state(0, rng)
    assert sum(1 for i, t in enumerate(state["order"]) if i != t) >= 6
    assert picture.act(state, picture.solution(state)[0], rng).solved
    out = picture.act(state, {"swaps": [[0, 1]]}, rng)  # one swap can't fix 6+ misplaced tiles
    assert not out.solved and out.attempt
    for bad in ({"swaps": [[0, 9]]}, {"swaps": "0,1"}, {"swaps": [[0]]}, {}):
        with pytest.raises(AppError):
            picture.act(state, bad, rng)


def test_rock_paper_scissors_first_to_two_and_a_lost_match_starts_again(monkeypatch):
    state = rps.new_state(0, random.Random())
    monkeypatch.setattr(rps, "computer_throw", lambda rng: "paper")
    assert rps.act(state, {"move": "rock"}, None).message.startswith("The computer wins")
    lost = rps.act(state, {"move": "rock"}, None)
    assert not lost.solved and state["you"] == state["cpu"] == 0 and state["matches_lost"] == 1
    monkeypatch.setattr(rps, "computer_throw", lambda rng: "scissors")
    assert not rps.act(state, {"move": "ROCK"}, None).solved
    won = rps.act(state, {"move": "rock"}, None)
    assert won.solved and not won.attempt and state["last"]["score"] == [2, 0]
    with pytest.raises(AppError):
        rps.act(state, {"move": "lizard"}, None)


def test_x_o_needs_a_win_and_the_computer_takes_its_own_wins():
    rng = random.Random()
    assert tictactoe.ai_move("OO.X.X...", rng) == 2  # O completes its row
    lost = {"board": "OO.X.X...", "games": 0, "last": None}
    out = tictactoe.act(lost, {"move": 8}, rng)
    assert not out.solved and lost["last"]["result"] == "lost" and lost["games"] == 1 and lost["board"] == "." * 9
    drawn = {"board": "XOXXOOOX.", "games": 2, "last": None}
    out = tictactoe.act(drawn, {"move": 8}, rng)
    assert not out.solved and drawn["last"]["result"] == "draw" and drawn["games"] == 3
    assert tictactoe.act({"board": "XX.OO....", "games": 0, "last": None}, {"move": 2}, rng).solved
    for bad in (0, 9, "2", None):
        with pytest.raises(AppError):
            tictactoe.act({"board": "X........", "games": 0, "last": None}, {"move": bad}, rng)


def test_x_o_can_really_be_won_against_the_computer():
    """Careful play (win if you can, block if you must, else centre/corner)
    beats the computer often - it isn't a perfect player."""
    rng = random.Random(2026)

    def x_move(board: str) -> int:
        empty = [i for i, ch in enumerate(board) if ch == "."]
        for mark in ("X", "O"):
            for i in empty:
                if tictactoe.winner(board[:i] + mark + board[i + 1:]) == mark:
                    return i
        return next(i for i in (4, 0, 2, 6, 8, 1, 3, 5, 7) if i in empty)

    wins = 0
    for _ in range(200):
        state = tictactoe.new_state(0, rng)
        while True:
            out = tictactoe.act(state, {"move": x_move(state["board"])}, rng)
            if out.solved:
                wins += 1
                break
            if state["board"] == "." * 9:  # lost or drawn - that game is over
                break
    assert wins >= 60  # well over a quarter of games


def test_a_team_keeps_its_puzzle_across_reloads_and_its_two_of_a_kind_differ(client):
    demo = seed(client, start=True)
    team = demo.teams["Dragon Warriors"]
    route = route_of(team["id"])
    scan(client, team, route[0].qr_token)
    first = client.get(f"{API}/puzzle/current", headers=team["headers"]).json()["puzzle"]
    assert client.get(f"{API}/me/state", headers=team["headers"]).json()["puzzle"] == first
    solve_puzzle(client, team)
    for loc in route[1:]:
        clear_checkpoint(client, team, loc)

    with SessionLocal() as db:
        sessions = db.scalars(select(PuzzleSession).where(PuzzleSession.team_id == team["id"])).all()
    assert len(sessions) == 8 and all(s.solved_at for s in sessions)
    dealt: dict[str, list] = {}
    for s in sessions:
        dealt.setdefault(s.kind, []).append(s.state.get("item", s.state.get("image")))
    assert dealt["scramble"][0] != dealt["scramble"][1]  # L01 and L07
    assert dealt["picture"][0] != dealt["picture"][1]  # L02 and L08


def test_games_are_played_against_the_server(client, monkeypatch):
    monkeypatch.setattr(puzzles, "kind_for_code", lambda code: "tictactoe")
    demo = seed(client, start=True)
    team = demo.teams["Border Runners"]
    scan(client, team, route_of(team["id"])[0].qr_token)
    assert play(client, team, {"move": "rock"}).status_code == 400
    res = play(client, team, {"move": 4}).json()
    board = res["puzzle"]["data"]["board"]
    assert res["solved"] is False and board[4] == "X" and board.count("O") == 1
    assert play(client, team, {"move": 4}).status_code == 400  # taken


def test_admin_sees_the_built_in_plan_and_attempt_counts(client, monkeypatch):
    demo = seed(client, start=True)
    plan = client.get(f"{API}/admin/checkpoints/puzzles", headers=demo.admin).json()
    assert [t["kind"] for t in plan["types"]] == ["scramble", "picture", "rps", "tictactoe", "riddle", "crossword"]
    assert {c["code"]: c["kind"] for c in plan["checkpoints"]}["L06"] == "crossword"

    monkeypatch.setattr(puzzles, "kind_for_code", lambda code: "riddle")
    team = demo.teams["Heart Breakers"]
    scan(client, team, route_of(team["id"])[0].qr_token)
    answer(client, team, "wrong")
    dash = client.get(f"{API}/admin/events/{demo.event_id}/dashboard", headers=demo.admin).json()
    assert next(r for r in dash["teams"] if r["id"] == team["id"])["puzzle_attempts"] == 1


def test_a_team_locked_before_the_upgrade_gets_its_puzzle_on_the_next_load(client):
    demo = seed(client, start=True)
    team = demo.teams["Spade Squad"]
    set_team(team["id"], status="PUZZLE_LOCKED", progress=1)  # as if mid-puzzle when the server was updated
    state = client.get(f"{API}/me/state", headers=team["headers"]).json()
    assert state["puzzle"]["checkpoint"] == 1 and open_session(team["id"]) is not None
