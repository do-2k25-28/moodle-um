"""Quiz attempt reading: start/resume an attempt and expose its questions.

The parser works on the same HTML the Moodle web UI renders. It targets the
stable pieces of that markup (``div.que``, ``.qtext``, ``input``/``select``
names, ``data-region="answer-label"``) rather than a specific theme.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .client import MoodleClient, MoodleError
from .parsers import clean_text, html_to_text, soup_of, soup_text

QUESTION_TYPES = {
    "multichoice",
    "truefalse",
    "shortanswer",
    "numerical",
    "match",
    "essay",
    "gapselect",
    "dragdrop",
    "ddwtos",
    "calculated",
    "calculatedsimple",
    "calculatedmulti",
    "ordering",
    "randomsamatch",
    "description",
}


def _question_type(question) -> str:
    classes = set(question.get("class", []))
    for name in QUESTION_TYPES:
        if name in classes:
            return name
    return "unknown"


def _question_slot(question) -> int | None:
    match = re.search(r"question-\d+-(\d+)", question.get("id", ""))
    if match:
        return int(match.group(1))
    number = question.select_one(".info .qno")
    if number:
        digits = re.sub(r"\D", "", number.get_text(" ", strip=True))
        if digits:
            return int(digits)
    return None


def _choice_label(soup: BeautifulSoup, control) -> str:
    labelledby = control.get("aria-labelledby")
    if labelledby:
        node = soup.find(id=labelledby)
        if node is not None:
            return clean_text(node.get_text(" ", strip=True))
    control_id = control.get("id")
    if control_id:
        label = soup.find("label", attrs={"for": control_id})
        if label is not None:
            return clean_text(label.get_text(" ", strip=True))
    parent = control.find_parent(class_=re.compile(r"(^|\s)r\d+(\s|$)"))
    if parent is not None:
        # Drop the input itself from the label text.
        clone = BeautifulSoup(str(parent), "lxml")
        for inp in clone.select("input"):
            inp.decompose()
        return clean_text(clone.get_text(" ", strip=True))
    return ""


def _is_correct(control) -> bool:
    parent = control.find_parent(class_=re.compile(r"(^|\s)r\d+(\s|$)"))
    return parent is not None and "correct" in (parent.get("class") or [])


def _parse_question(soup: BeautifulSoup, question) -> dict[str, Any]:
    slot = _question_slot(question)
    qtype = _question_type(question)
    qtext_node = question.select_one(".qtext") or question.select_one(
        ".formulation"
    )
    text = html_to_text(str(qtext_node), "") if qtext_node else ""
    if not text:
        text = soup_text(qtext_node)

    state = soup_text(question.select_one(".info .state"))
    grade = soup_text(question.select_one(".info .grade"))

    choices = []
    for control in question.select("input[type=radio], input[type=checkbox]"):
        name = control.get("name") or ""
        if not name or "flagged" in name:
            continue
        choices.append(
            {
                "name": name,
                "value": control.get("value") or "",
                "label": _choice_label(soup, control),
                "selected": control.has_attr("checked"),
                "correct": _is_correct(control),
                "kind": "choice",
            }
        )

    text_inputs = []
    for control in question.select("input[type=text], input[type=number], textarea"):
        name = control.get("name") or ""
        if not name or "flagged" in name:
            continue
        text_inputs.append(
            {
                "name": name,
                "kind": "text" if control.name == "input" else "textarea",
                "value": control.get("value") or control.get_text() or "",
                "label": _choice_label(soup, control),
            }
        )

    selects = []
    for select in question.select("select"):
        name = select.get("name") or ""
        if not name or "flagged" in name:
            continue
        options = []
        for option in select.select("option"):
            options.append(
                {
                    "value": option.get("value") or "",
                    "label": clean_text(option.get_text(" ", strip=True)),
                    "selected": option.has_attr("selected"),
                }
            )
        selects.append({"name": name, "kind": "select", "options": options})

    return {
        "slot": slot,
        "number": slot,
        "type": qtype,
        "text": text,
        "state": state,
        "grade": grade,
        "choices": choices,
        "text_inputs": text_inputs,
        "selects": selects,
        "raw_answer_names": sorted(
            {c["name"] for c in choices}
            | {c["name"] for c in text_inputs}
            | {c["name"] for c in selects}
        ),
    }


def parse_attempt_page(
    html: str, base_url: str = "", attemptid: int | None = None
) -> dict[str, Any]:
    """Parse a Moodle quiz attempt/review page into questions and controls."""
    soup = soup_of(html)
    questions = [_parse_question(soup, q) for q in soup.select("div.que")]

    if attemptid is None:
        hidden = soup.select_one("input[name='attempt']")
        if hidden and (hidden.get("value") or "").isdigit():
            attemptid = int(hidden["value"])
    thispage = soup.select_one("input[name='thispage']")
    page = int(thispage["value"]) if thispage and thispage.get("value", "").isdigit() else 0

    timeleft = soup_text(
        soup.select_one("#quiz-timer, .quiz-timer, [data-region='quiz-timer']")
    )
    if not timeleft:
        timer = soup.select_one(".timeleft")
        timeleft = soup_text(timer)

    return {
        "attemptid": attemptid,
        "page": page,
        "timeleft": timeleft,
        "question_count": len(questions),
        "questions": questions,
        "text": html_to_text(html, base_url)[:8000],
    }


def _form_fields(form, soup: BeautifulSoup) -> dict[str, str]:
    fields: dict[str, str] = {}
    for control in form.select("input[name]"):
        name = control.get("name")
        if not name:
            continue
        if (control.get("type") or "").lower() in ("submit", "button", "reset"):
            continue
        fields[name] = control.get("value") or ""
    return fields


async def start_quiz(client: MoodleClient, cmid: int) -> dict[str, Any]:
    """Start or resume a quiz attempt, then return its questions."""
    html, final = await client.get_text(f"/mod/quiz/view.php?id={cmid}")
    soup = soup_of(html)

    # An attempt is already in progress: follow the "Continue" link.
    existing = soup.select_one('a[href*="attempt.php?attempt="]')
    if existing is not None:
        url = urljoin(final, existing["href"])
        attempt_html, attempt_url = await client.get_text(url)
        return parse_attempt_page(attempt_html, attempt_url)

    form = None
    for candidate in soup.select("form"):
        if "startattempt.php" in (candidate.get("action") or ""):
            form = candidate
            break

    if form is None:
        link = soup.select_one('a[href*="startattempt.php"]')
        if link is not None:
            url = urljoin(final, link["href"])
            attempt_html, attempt_url = await client.get_text(url)
            if "attempt.php" in attempt_url:
                return parse_attempt_page(attempt_html, attempt_url)
            return {
                "started": False,
                "preflight": True,
                "url": attempt_url,
                "text": html_to_text(attempt_html, attempt_url),
            }
        raise MoodleError(
            "Moodle did not offer a start-attempt form. The quiz may be closed, "
            "already finished, or restricted (password/SEB)."
        )

    action = urljoin(final, form["action"])
    fields = _form_fields(form, soup)
    response_html, response_url = await client.post_form(action, fields)
    if "/mod/quiz/attempt.php" in response_url or soup_of(response_html).select(
        "div.que"
    ):
        return parse_attempt_page(response_html, response_url)

    # A preflight form (password, honour statement, SEB check, …).
    return {
        "started": False,
        "preflight": True,
        "url": response_url,
        "text": html_to_text(response_html, response_url),
        "forms": [
            {
                "action": urljoin(response_url, f.get("action") or ""),
                "fields": _form_fields(f, soup_of(response_html)),
            }
            for f in soup_of(response_html).select("form")
        ],
    }


async def get_attempt(
    client: MoodleClient, attemptid: int, page: int = 0
) -> dict[str, Any]:
    """Read one page of an in-progress attempt."""
    html, final = await client.get_text(
        f"/mod/quiz/attempt.php?attempt={attemptid}&page={page}"
    )
    if "/mod/quiz/review.php" in final or "/mod/quiz/summary.php" in final:
        result = parse_attempt_page(html, final, attemptid)
        result.update(
            {
                "finished": True,
                "review_url": final,
            }
        )
        # The review page text duplicates the structured questions; drop it
        # to keep MCP responses small.
        result.pop("text", None)
        return result
    return parse_attempt_page(html, final, attemptid)


def _attempt_form(soup: BeautifulSoup):
    form = soup.select_one("form#responseform")
    if form is not None:
        return form
    for candidate in soup.select("form"):
        if candidate.select_one("input[name='attempt']"):
            return candidate
    return None


def _attempt_fields(form) -> dict[str, str]:
    """Current values of a quiz response form, suitable for re-posting."""
    fields: dict[str, str] = {}
    for control in form.select("input[name]"):
        name = control.get("name")
        if not name:
            continue
        kind = (control.get("type") or "text").lower()
        if kind in ("submit", "button", "reset", "file"):
            continue
        if kind in ("radio", "checkbox"):
            if control.has_attr("checked"):
                fields[name] = control.get("value") or "1"
            continue
        fields[name] = control.get("value") or ""
    for area in form.select("textarea[name]"):
        fields[area["name"]] = area.get_text()
    for select in form.select("select[name]"):
        chosen = select.select_one("option[selected]")
        if chosen is not None:
            fields[select["name"]] = chosen.get("value") or ""
    return fields


def _strip_option_prefix(label: str) -> str:
    return re.sub(r"^\s*[a-z][.)]\s*", "", label, flags=re.IGNORECASE).strip()


def _match_choice(choices: list[dict], value: Any) -> dict | None:
    needle = str(value).strip().lower()
    for choice in choices:
        if str(choice.get("value", "")).strip().lower() == needle:
            return choice
    for choice in choices:
        label = _strip_option_prefix(str(choice.get("label", ""))).lower()
        if label == needle or (needle and needle in label):
            return choice
    for choice in choices:
        label = str(choice.get("label", ""))
        prefix = re.match(r"^\s*([a-z])[.)]", label, re.IGNORECASE)
        if prefix and prefix.group(1).lower() == needle:
            return choice
    return None


def resolve_answers(parsed: dict, answers: dict[str, Any]) -> dict[str, str]:
    """Map ``{"1": "b"}`` style answers to raw Moodle input names.

    Keys may also be raw input names (``q42:1_answer``). Values may be a choice
    label, a choice value, a text answer, or a list of labels for
    multiple-response questions.
    """
    by_slot = {str(q.get("slot")): q for q in parsed.get("questions", [])}
    raw_names = {
        name
        for q in parsed.get("questions", [])
        for name in q.get("raw_answer_names", [])
    }
    resolved: dict[str, str] = {}

    for key, value in answers.items():
        key = str(key)
        if key in raw_names:
            resolved[key] = "" if value is None or value is False else str(value)
            continue

        question = by_slot.get(key)
        if question is None:
            raise MoodleError(f"Unknown question or input: {key}")

        choices = question.get("choices") or []
        if choices:
            names = {choice["name"] for choice in choices}
            if len(names) == 1:
                # Radio / true-false: one value under one input name.
                choice = _match_choice(choices, value)
                if choice is None:
                    raise MoodleError(
                        f"No choice matching {value!r} for question {key}"
                    )
                resolved[choice["name"]] = choice["value"]
            else:
                # Multiple response: each selected name is 1, the rest omitted.
                wanted = value if isinstance(value, (list, tuple, set)) else [value]
                matched = []
                for item in wanted:
                    choice = _match_choice(choices, item)
                    if choice is None:
                        raise MoodleError(
                            f"No choice matching {item!r} for question {key}"
                        )
                    matched.append(choice)
                for choice in choices:
                    resolved[choice["name"]] = (
                        "1" if choice in matched else ""
                    )
            continue

        text_inputs = question.get("text_inputs") or []
        if text_inputs:
            resolved[text_inputs[0]["name"]] = str(value)
            continue

        selects = question.get("selects") or []
        if selects:
            select = selects[0]
            needle = str(value).strip().lower()
            option = next(
                (
                    opt
                    for opt in select.get("options", [])
                    if str(opt.get("value", "")).lower() == needle
                    or str(opt.get("label", "")).strip().lower() == needle
                ),
                None,
            )
            if option is None:
                raise MoodleError(
                    f"No option matching {value!r} for question {key}"
                )
            resolved[select["name"]] = option["value"]
            continue

        raise MoodleError(f"Question {key} has no answer field")

    return resolved


async def save_answers(
    client: MoodleClient,
    attemptid: int,
    answers: dict[str, str],
    page: int | None = None,
    finish: bool = False,
) -> dict[str, Any]:
    """Save answers for the current page (or finish/submit the attempt)."""
    url = f"/mod/quiz/attempt.php?attempt={attemptid}"
    if page is not None:
        url += f"&page={page}"
    html, final = await client.get_text(url)
    if "/mod/quiz/review.php" in final:
        result = parse_attempt_page(html, final, attemptid)
        result.update({"finished": True, "review_url": final})
        result.pop("text", None)
        return result

    soup = soup_of(html)
    form = _attempt_form(soup)
    if form is None:
        raise MoodleError(
            "No response form found. The attempt may be closed or already submitted."
        )

    fields = _attempt_fields(form)
    for name, value in answers.items():
        if value is None or value is False or str(value) == "":
            fields.pop(name, None)
        else:
            fields[name] = str(value)

    if finish:
        fields["finishattempt"] = "1"
        fields["timeup"] = "0"
        fields.pop("next", None)
    else:
        fields["next"] = "1"
        fields["timeup"] = "0"
        thispage = int(fields.get("thispage", page or 0) or 0)
        nextpage = fields.get("nextpage") or ""
        if not nextpage or nextpage == "-1":
            # Last page: save in place instead of accidentally finishing.
            nextpage = str(thispage)
        fields["nextpage"] = nextpage

    action = urljoin(final, form.get("action") or final)
    response_html, response_url = await client.post_form(action, fields)
    if "/mod/quiz/review.php" in response_url or "/mod/quiz/summary.php" in response_url:
        result = parse_attempt_page(response_html, response_url, attemptid)
        result.update({"finished": True, "review_url": response_url})
        result.pop("text", None)
        return result
    return parse_attempt_page(response_html, response_url, attemptid)


async def solve_attempt(
    client: MoodleClient,
    attemptid: int,
    answers: dict[str, Any],
    page: int | None = None,
) -> dict[str, Any]:
    """Resolve user-friendly answers against the attempt page and save them."""
    url = f"/mod/quiz/attempt.php?attempt={attemptid}"
    if page is not None:
        url += f"&page={page}"
    html, final = await client.get_text(url)
    parsed = parse_attempt_page(html, final, attemptid)
    resolved = resolve_answers(parsed, answers)
    return await save_answers(client, attemptid, resolved, page=page, finish=False)


async def submit_attempt(
    client: MoodleClient, attemptid: int, page: int | None = None
) -> dict[str, Any]:
    """Finish and submit the attempt."""
    return await save_answers(client, attemptid, {}, page=page, finish=True)
