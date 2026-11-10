import asyncio
from pathlib import Path
from urllib.parse import parse_qs

import httpx

from moodle_um.client import MoodleClient
from moodle_um.quiz import (
    parse_attempt_page,
    resolve_answers,
    save_answers,
    solve_attempt,
    start_quiz,
    submit_attempt,
)

FIXTURES = Path(__file__).parent / "fixtures" / "quiz"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_multichoice_question_and_choices():
    result = parse_attempt_page(
        fixture("multichoice.html"), "https://moodle.example/mod/quiz/attempt.php"
    )
    assert result["attemptid"] == 42
    assert result["timeleft"] == "00:10:00"
    assert result["question_count"] == 1

    question = result["questions"][0]
    assert question["slot"] == 1
    assert question["type"] == "multichoice"
    assert "2 + 2" in question["text"]
    assert len(question["choices"]) == 3
    assert question["choices"][0]["value"] == "0"
    assert "3" in question["choices"][0]["label"]
    assert question["choices"][1]["correct"] is True
    assert question["raw_answer_names"] == ["q100:1_answer"]


def test_parse_mixed_question_types():
    result = parse_attempt_page(fixture("mixed.html"), "https://moodle.example/")
    by_type = {q["type"]: q for q in result["questions"]}

    assert set(by_type) == {
        "truefalse",
        "shortanswer",
        "match",
        "essay",
        "gapselect",
    }
    assert [c["label"] for c in by_type["truefalse"]["choices"]] == ["True", "False"]
    assert by_type["shortanswer"]["text_inputs"][0]["name"] == "q100:3_answer"
    assert len(by_type["match"]["selects"]) == 2
    assert by_type["essay"]["text_inputs"][0]["kind"] == "textarea"
    assert [s["name"] for s in by_type["gapselect"]["selects"]] == [
        "q100:6_answer1",
        "q100:6_answer2",
    ]


def test_start_quiz_posts_form_and_parses_attempt():
    async def run() -> dict:
        view_html = fixture("view_start.html")
        attempt_html = fixture("multichoice.html")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/mod/quiz/view.php":
                return httpx.Response(200, text=view_html)
            if request.url.path == "/mod/quiz/startattempt.php":
                return httpx.Response(
                    303,
                    headers={"Location": "/mod/quiz/attempt.php?attempt=42&cmid=1"},
                )
            if request.url.path == "/mod/quiz/attempt.php":
                return httpx.Response(200, text=attempt_html)
            return httpx.Response(404)

        client = MoodleClient()
        client.site = "http://moodle.test"
        client.sesskey = "test-sesskey"
        client._bootstrapped = True
        client.http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        )
        try:
            return await start_quiz(client, 1)
        finally:
            await client.http.aclose()

    result = asyncio.run(run())
    assert result["attemptid"] == 42
    assert result["question_count"] == 1
    assert result["questions"][0]["type"] == "multichoice"


def _mock_client(handler) -> MoodleClient:
    client = MoodleClient()
    client.site = "http://moodle.test"
    client.sesskey = "test-sesskey"
    client._bootstrapped = True
    client.http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    )
    return client


def test_resolve_answers_by_label_value_and_letter():
    parsed = parse_attempt_page(fixture("attempt_form.html"))
    raw = resolve_answers(
        parsed,
        {"1": "b", "2": "Paris", "3": ["A", "C"]},
    )
    assert raw["q42:1_answer"] == "1"
    assert raw["q42:2_answer"] == "Paris"
    assert raw["q42:3_choice0"] == "1"
    assert raw["q42:3_choice1"] == ""
    assert raw["q42:3_choice2"] == "1"


def test_save_answers_posts_selected_values():
    posts: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(parse_qs(request.content.decode()))
            return httpx.Response(
                303,
                headers={"Location": "/mod/quiz/attempt.php?attempt=42&page=1"},
            )
        return httpx.Response(200, text=fixture("attempt_form.html"))

    async def run():
        client = _mock_client(handler)
        try:
            return await save_answers(
                client, 42, {"q42:1_answer": "1", "q42:2_answer": "Paris"}
            )
        finally:
            await client.http.aclose()

    result = asyncio.run(run())
    assert result["attemptid"] == 42
    assert posts, "expected a POST to processattempt.php"
    post = posts[0]
    assert post["q42:1_answer"] == ["1"]
    assert post["q42:2_answer"] == ["Paris"]
    assert post["next"] == ["1"]
    assert "finishattempt" not in post


def test_submit_sends_finishattempt_and_parses_review():
    posts: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(parse_qs(request.content.decode()))
            return httpx.Response(
                303,
                headers={"Location": "/mod/quiz/review.php?attempt=42&cmid=1"},
            )
        if request.url.path == "/mod/quiz/review.php":
            return httpx.Response(200, text=fixture("multichoice.html"))
        return httpx.Response(200, text=fixture("attempt_form.html"))

    async def run():
        client = _mock_client(handler)
        try:
            return await submit_attempt(client, 42)
        finally:
            await client.http.aclose()

    result = asyncio.run(run())
    assert result["finished"] is True
    assert posts[0]["finishattempt"] == ["1"]


def test_solve_attempt_maps_user_answers():
    posts: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(parse_qs(request.content.decode()))
            return httpx.Response(
                303,
                headers={"Location": "/mod/quiz/attempt.php?attempt=42&page=1"},
            )
        return httpx.Response(200, text=fixture("attempt_form.html"))

    async def run():
        client = _mock_client(handler)
        try:
            return await solve_attempt(
                client, 42, {"1": "b", "2": "Paris", "3": ["A", "C"]}
            )
        finally:
            await client.http.aclose()

    result = asyncio.run(run())
    assert result["attemptid"] == 42
    post = posts[0]
    assert post["q42:1_answer"] == ["1"]
    assert post["q42:2_answer"] == ["Paris"]
    assert post["q42:3_choice0"] == ["1"]
    assert "q42:3_choice1" not in post
    assert post["q42:3_choice2"] == ["1"]
