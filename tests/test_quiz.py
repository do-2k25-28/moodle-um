import asyncio
from pathlib import Path

import httpx

from moodle_um.client import MoodleClient
from moodle_um.quiz import parse_attempt_page, start_quiz

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
