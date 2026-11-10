"""Domain layer: courses, assignments, quizzes, grades, calendar."""

from __future__ import annotations

import html as html_lib
import re
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .client import MoodleClient, MoodleError
from .parsers import clean_text, html_to_text, soup_of, soup_text


# --------------------------------------------------------------------------
# Generic helpers
# --------------------------------------------------------------------------
def _int_or_none(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _course_id_from_url(url: str) -> int | None:
    match = re.search(r"[?&]id=(\d+)", url)
    return int(match.group(1)) if match else None


def _first_link(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node and node.get("href"):
            return node["href"]
    return ""


def _section_slug(text: str) -> str:
    text = text.lower().strip()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


# --------------------------------------------------------------------------
# Courses
# --------------------------------------------------------------------------
async def list_courses(client: MoodleClient, query: str | None = None) -> list[dict]:
    """List the current user's enrolled courses."""
    courses: list[dict] = []
    try:
        data = await client.ajax(
            "core_course_get_enrolled_courses_by_timeline_classification",
            {
                "classification": "all",
                "limit": 0,
                "offset": 0,
                "sort": "fullname",
            },
        )
        for course in (data or {}).get("courses", []):
            courses.append(
                {
                    "id": course.get("id"),
                    "name": clean_text(html_lib.unescape(course.get("fullname") or "")),
                    "shortname": clean_text(course.get("shortname")),
                    "category": clean_text(course.get("coursecategory")),
                    "summary": clean_text(course.get("summary")),
                    "startdate": course.get("startdate"),
                    "enddate": course.get("enddate"),
                    "hidden": course.get("hidden"),
                    "progress": course.get("progress"),
                    "url": f"{client.site}/course/view.php?id={course.get('id')}",
                }
            )
    except MoodleError:
        courses = []

    # The dashboard block also lists courses that the timeline API omits
    # (old/hidden semester courses). Merge them in.
    known = {course["id"] for course in courses}
    for page in ("/my/", "/my/courses.php"):
        try:
            html, final = await client.get_text(page)
        except Exception:
            continue
        soup = soup_of(html)
        for a in soup.select('a[href*="course/view.php?id="]'):
            href = urljoin(final, a["href"])
            cid = _course_id_from_url(href)
            if not cid or cid == 1 or cid in known:
                continue
            name = clean_text(html_lib.unescape(a.get_text(" ", strip=True)))
            if not name:
                parent = a.find_parent(["div", "li"])
                if parent:
                    heading = parent.find(["h3", "h4", "h5"])
                    if heading:
                        name = clean_text(heading.get_text(" ", strip=True))
            if not name:
                continue
            known.add(cid)
            courses.append(
                {
                    "id": cid,
                    "name": name,
                    "shortname": "",
                    "category": "",
                    "summary": "",
                    "url": f"{client.site}/course/view.php?id={cid}",
                }
            )
    courses.sort(key=lambda c: c["name"].lower())

    if query:
        needle = query.lower()
        courses = [
            c
            for c in courses
            if needle in c["name"].lower() or needle in (c.get("shortname") or "").lower()
        ]
    return courses


async def get_course(client: MoodleClient, courseid: int) -> dict:
    """Return the structure of a course: sections, activities and files."""
    html, final = await client.get_text(f"/course/view.php?id={courseid}")
    soup = soup_of(html)
    title = (
        soup_text(soup.select_one("h1"))
        or soup_text(soup.select_one(".page-header-headings"))
        or f"Course {courseid}"
    )
    sections: list[dict] = []
    seen_sections: set[str] = set()

    candidates = soup.select("li.section, div.section")
    for order, section in enumerate(candidates):
        sid = (
            section.get("data-number")
            or section.get("data-section")
            or section.get("data-sectionid")
            or _int_or_none(section.get("id"))
        )
        key = str(sid if sid is not None else order)
        if key in seen_sections:
            continue
        seen_sections.add(key)
        name_node = section.select_one(".sectionname, h3.sectionname, h3")
        name = clean_text(name_node.get_text(" ", strip=True)) if name_node else ""
        if not name:
            name = clean_text(section.get("data-sectionname") or "")
        if not name:
            name = "Général" if key == "0" else f"Section {key}"
        summary_node = section.select_one(".summarytext, .section-summary")
        activities = []
        for li in section.select("li.activity"):
            activity = _parse_activity(li, final)
            if activity:
                activities.append(activity)
        sections.append(
            {
                "id": key,
                "name": name,
                "summary": clean_text(summary_node.get_text(" ", strip=True))
                if summary_node
                else "",
                "activities": activities,
            }
        )

    # Fallback: some course formats use a flat activity list.
    if not sections:
        activities = [
            a for li in soup.select("li.activity") if (a := _parse_activity(li, final))
        ]
        if activities:
            sections = [
                {"id": "0", "name": "Activités", "summary": "", "activities": activities}
            ]

    return {
        "id": courseid,
        "name": title,
        "url": final,
        "sections": sections,
        "activity_count": sum(len(s["activities"]) for s in sections),
    }


def _parse_activity(li, base_url: str) -> dict | None:
    cmid = _int_or_none(li.get("data-id")) or _int_or_none(li.get("id"))
    if not cmid:
        return None
    classes = " ".join(li.get("class", []))
    mod_match = re.search(r"modtype_(\w+)", classes)
    modname = li.get("data-modname") or (mod_match.group(1) if mod_match else "")
    if not modname:
        href = li.select_one("a[href*='/mod/']")
        if href and href.get("href"):
            path_match = re.search(r"/mod/(\w+)/", href["href"])
            if path_match:
                modname = path_match.group(1)
    link = li.select_one(
        ".activityname a[href], a.aalink[href], a[href*='/mod/'][href*='view.php']"
    )
    url = urljoin(base_url, link["href"]) if link and link.get("href") else ""
    name = clean_text(link.get_text(" ", strip=True)) if link else ""
    if not name:
        name = clean_text(li.get("data-activityname") or "")
    if not name:
        instancename = li.select_one(".instancename")
        name = clean_text(instancename.get_text(" ", strip=True)) if instancename else ""
    if not name:
        named = li.select_one("[data-activityname]")
        if named:
            name = clean_text(named.get("data-activityname") or "")
    # Remove the trailing type label ("Devoir", "Test", ...) Moodle appends.
    name = re.sub(
        r"\s+(Devoir|Test|Quiz|Forum|Ressource|Fichier|URL|Page|Dossier|Leçon|Sondage|Choix)\s*$",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    dates = soup_text(li.select_one(".activity-dates"))
    alt = soup_text(li.select_one(".activity-altcontent"))
    availability = soup_text(li.select_one(".availabilityinfo"))
    files = []
    for a in li.select("a[href*='pluginfile.php']"):
        files.append(
            {
                "name": clean_text(a.get_text(" ", strip=True)),
                "url": urljoin(base_url, a["href"]),
            }
        )
    return {
        "cmid": cmid,
        "modname": modname,
        "name": name,
        "url": url,
        "dates": dates,
        "description": alt,
        "availability": availability,
        "files": files,
        "hidden": "hidden" in classes or "dimmed" in classes,
    }


# --------------------------------------------------------------------------
# Assignments
# --------------------------------------------------------------------------
async def list_assignments(client: MoodleClient, courseid: int) -> list[dict]:
    """List assignments in a course via mod/assign/index.php."""
    html, final = await client.get_text(f"/mod/assign/index.php?id={courseid}")
    soup = soup_of(html)
    rows = []
    table = soup.select_one("table.generaltable")
    if table:
        headers = [clean_text(th.get_text(" ", strip=True)) for th in table.select("thead th")]
        idx = _header_index(headers)
        for tr in table.select("tbody tr"):
            cells = tr.select("td")
            if not cells:
                continue
            link = tr.select_one('a[href*="/mod/assign/view.php?id="]')
            if not link:
                continue
            cmid = _course_id_from_url(link["href"])
            values = [clean_text(td.get_text(" ", strip=True)) for td in cells]
            rows.append(
                {
                    "cmid": cmid,
                    "name": clean_text(link.get_text(" ", strip=True)),
                    "url": urljoin(final, link["href"]),
                    "due": _cell(values, idx.get("due")),
                    "submission": _cell(values, idx.get("submission")),
                    "grade": _cell(values, idx.get("grade")),
                    "status": _cell(values, idx.get("status")),
                    "columns": values,
                }
            )
    if not rows:
        # Fall back to the course page modules.
        course = await get_course(client, courseid)
        for section in course["sections"]:
            for activity in section["activities"]:
                if activity["modname"] == "assign":
                    rows.append(
                        {
                            "cmid": activity["cmid"],
                            "name": activity["name"],
                            "url": activity["url"],
                            "due": activity["dates"],
                            "submission": activity["description"],
                            "grade": "",
                            "status": "",
                        }
                    )
    return rows


def _header_index(headers: list[str]) -> dict[str, int]:
    def normalize(value: str) -> str:
        import unicodedata

        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
        return value.lower()

    normalized = [normalize(h) for h in headers]
    mapping: dict[str, int] = {}
    for i, header in enumerate(normalized):
        if "echeance" in header or "due" in header or "date limite" in header or "limite" in header:
            mapping.setdefault("due", i)
        elif "remis" in header or "remise" in header or "submission" in header or "travail" in header:
            mapping.setdefault("submission", i)
        elif "note" in header or "grade" in header:
            mapping.setdefault("grade", i)
        elif "statut" in header or "status" in header:
            mapping.setdefault("status", i)
    return mapping


def _cell(values: list[str], index: int | None) -> str:
    if index is None or index >= len(values):
        return ""
    return values[index]


async def get_assignment(client: MoodleClient, cmid: int) -> dict:
    """Return details and submission state for one assignment."""
    html, final = await client.get_text(f"/mod/assign/view.php?id={cmid}")
    soup = soup_of(html)
    title = (
        soup_text(soup.select_one("h1"))
        or soup_text(soup.select_one(".page-header-headings"))
        or f"Assignment {cmid}"
    )
    course_link = soup.select_one('.breadcrumb a[href*="/course/view.php?id="]') or soup.select_one(
        'a[href*="/course/view.php?id="]'
    )
    courseid = _course_id_from_url(course_link["href"]) if course_link else None

    info: dict[str, str] = {}
    for table in soup.select("table.generaltable"):
        for tr in table.select("tr"):
            th = tr.select_one("th")
            td = tr.select_one("td")
            if th and td:
                info[clean_text(th.get_text(" ", strip=True))] = clean_text(
                    td.get_text(" ", strip=True)
                )

    activity_info = soup.select_one("[data-region='activity-information']")
    opened = due = ""
    if activity_info:
        lines = [
            clean_text(line)
            for line in activity_info.get_text("\n", strip=True).split("\n")
            if clean_text(line)
        ]
        for i, line in enumerate(lines):
            if line.startswith(("Opened", "Ouvert")) and i + 1 < len(lines):
                opened = lines[i + 1]
            if line.startswith(("Due", "À rendre", "A rendre")) and i + 1 < len(lines):
                due = lines[i + 1]
        if opened:
            info.setdefault("Opened", opened)
        if due:
            info.setdefault("Due", due)

    intro = soup.select_one("#intro, .intro")
    intro_text = clean_text(intro.get_text(" ", strip=True)) if intro else ""
    intro_links = []
    if intro:
        for a in intro.select("a[href]"):
            href = urljoin(final, a["href"])
            intro_links.append(
                {
                    "name": clean_text(a.get_text(" ", strip=True)),
                    "url": href,
                }
            )

    status_node = soup.select_one(".submissionstatustable")
    if status_node:
        for noisy in status_node.select(".submissioncomments, .comment-area, form"):
            noisy.decompose()
    status_text = soup_text(status_node)
    status_text = re.split(r"Submission comments|Commentaires", status_text)[0].strip()
    for key in ("Submission comments", "Commentaires"):
        info.pop(key, None)
    feedback_text = soup_text(soup.select_one(".feedbacktable"))
    grade_text = soup_text(soup.select_one(".grade"))

    actions = []
    for a in soup.select("a[href*='action=']"):
        href = urljoin(final, a["href"])
        text = clean_text(a.get_text(" ", strip=True))
        if text:
            actions.append({"name": text, "url": href})

    edit_form = None
    remove_form = None
    for form in soup.select("form"):
        action_input = form.select_one("input[name='action']")
        action_value = (action_input.get("value") if action_input else "") or ""
        if action_value == "editsubmission":
            edit_form = form
        elif action_value == "removesubmissionconfirm":
            remove_form = form

    edit_url = ""
    if edit_form is not None:
        cmid_input = edit_form.select_one("input[name='id']")
        edit_url = urljoin(
            final,
            f"/mod/assign/view.php?id={cmid_input.get('value') if cmid_input else cmid}&action=editsubmission",
        )
    remove_url = ""
    if remove_form is not None:
        cmid_input = remove_form.select_one("input[name='id']")
        remove_url = urljoin(
            final,
            f"/mod/assign/view.php?id={cmid_input.get('value') if cmid_input else cmid}&action=removesubmissionconfirm",
        )

    submitted_files = []
    for table in soup.select(".submissionstatustable, .submissionnotgraded"):
        for a in table.select("a[href*='pluginfile.php']"):
            submitted_files.append(
                {
                    "name": clean_text(a.get_text(" ", strip=True)),
                    "url": urljoin(final, a["href"]),
                }
            )

    return {
        "cmid": cmid,
        "assignid": _int_or_none(
            soup.select_one("input[name='assignmentid']").get("value")
            if soup.select_one("input[name='assignmentid']")
            else None
        ),
        "courseid": courseid,
        "name": title,
        "url": final,
        "info": info,
        "opened": opened,
        "due": due,
        "intro": intro_text,
        "intro_links": intro_links,
        "status": status_text,
        "feedback": feedback_text,
        "grade": grade_text,
        "actions": actions,
        "submitted_files": submitted_files,
        "edit_submission_url": edit_url,
        "remove_submission_url": remove_url,
        "can_edit": bool(edit_url),
        "can_remove": bool(remove_url),
        "text": html_to_text(html, final)[:6000],
    }


# --------------------------------------------------------------------------
# Quizzes
# --------------------------------------------------------------------------
async def list_quizzes(client: MoodleClient, courseid: int) -> list[dict]:
    html, final = await client.get_text(f"/mod/quiz/index.php?id={courseid}")
    soup = soup_of(html)
    quizzes: dict[int, dict] = {}
    for tr in soup.select("table.generaltable tbody tr, table.generaltable tr"):
        link = tr.select_one('a[href*="view.php?id="]')
        if not link:
            continue
        cmid = _course_id_from_url(link["href"])
        if not cmid:
            continue
        values = [clean_text(td.get_text(" ", strip=True)) for td in tr.select("td")]
        quizzes[cmid] = {
            "cmid": cmid,
            "name": clean_text(link.get_text(" ", strip=True)),
            "url": urljoin(final, link["href"]),
            "columns": values,
        }
    return list(quizzes.values())


async def get_quiz(client: MoodleClient, cmid: int) -> dict:
    html, final = await client.get_text(f"/mod/quiz/view.php?id={cmid}")
    soup = soup_of(html)
    title = (
        soup_text(soup.select_one("h1"))
        or soup_text(soup.select_one(".page-header-headings"))
        or f"Quiz {cmid}"
    )
    info: dict[str, str] = {}
    for table in soup.select("table.generaltable"):
        for tr in table.select("tr"):
            th = tr.select_one("th")
            td = tr.select_one("td")
            if th and td:
                info[clean_text(th.get_text(" ", strip=True))] = clean_text(
                    td.get_text(" ", strip=True)
                )
    attempts = []
    seen_attempts: set[str] = set()
    for a in soup.select('a[href*="review.php?attempt="], a[href*="attempt.php?attempt="]'):
        href = urljoin(final, a["href"])
        match = re.search(r"[?&]attempt=(\d+)", href)
        if not match or match.group(1) in seen_attempts:
            continue
        seen_attempts.add(match.group(1))
        attempts.append(
            {
                "attemptid": int(match.group(1)),
                "name": clean_text(a.get_text(" ", strip=True)),
                "url": href,
                "state": "review" if "review.php" in href else "in_progress",
            }
        )

    start_url = ""
    start_link = soup.select_one('a[href*="startattempt.php"]')
    if start_link:
        start_url = urljoin(final, start_link["href"])
    else:
        for form in soup.select("form"):
            action = form.get("action") or ""
            if "startattempt.php" in action:
                start_url = urljoin(final, action)
                break

    return {
        "cmid": cmid,
        "name": title,
        "url": final,
        "info": info,
        "attempts": attempts,
        "start_url": start_url,
        "can_start": bool(start_url),
        "text": html_to_text(html, final)[:5000],
    }


# --------------------------------------------------------------------------
# Grades
# --------------------------------------------------------------------------
async def get_grades(client: MoodleClient, courseid: int) -> dict:
    html, final = await client.get_text(f"/grade/report/user/index.php?id={courseid}")
    soup = soup_of(html)
    title = (
        soup_text(soup.select_one("h1"))
        or soup_text(soup.select_one(".page-header-headings"))
        or "Grades"
    )
    items = []
    table = soup.select_one("table.user-grade")
    if table:
        headers = [clean_text(th.get_text(" ", strip=True)) for th in table.select("thead th")]
        for tr in table.select("tbody tr"):
            cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.select("td")]
            if cells:
                items.append({"columns": cells})
    return {
        "courseid": courseid,
        "course": title,
        "url": final,
        "headers": headers if table else [],
        "items": items,
        "text": html_to_text(html, final)[:6000],
    }


# --------------------------------------------------------------------------
# Calendar / upcoming
# --------------------------------------------------------------------------
async def upcoming(client: MoodleClient, limit: int = 30) -> list[dict]:
    now = int(time.time())
    try:
        data = await client.ajax(
            "core_calendar_get_action_events_by_timesort",
            {
                "timesortfrom": now,
                "limitnum": limit,
                "limittononsuspendedevents": True,
            },
        )
        events = []
        for event in (data or {}).get("events", []):
            events.append(
                {
                    "name": clean_text(event.get("name")),
                    "timesort": event.get("timesort"),
                    "formatted_time": event.get("formattedtime"),
                    "url": event.get("url"),
                    "course": clean_text((event.get("course") or {}).get("fullname")),
                    "action": (event.get("action") or {}).get("name"),
                    "description": clean_text(event.get("description")),
                    "overdue": event.get("overdue"),
                }
            )
        return events
    except MoodleError:
        html, final = await client.get_text("/calendar/view.php?view=upcoming")
        text = html_to_text(html, final)
        return [{"text": text[:5000], "url": final}]


# --------------------------------------------------------------------------
# Generic page
# --------------------------------------------------------------------------
async def get_page(client: MoodleClient, url: str) -> dict:
    response = await client.fetch(url)
    final = str(response.url)
    if "/login/" in final and "authCAS" not in final:
        # Session expired: get_text() will renew it and retry.
        html, final = await client.get_text(url)
        response = None
        content_type = "text/html"
    else:
        content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "text/" not in content_type:
        return {
            "url": final,
            "title": final.rsplit("/", 1)[-1],
            "binary": True,
            "content_type": content_type,
            "bytes": len(response.content),
            "hint": "This URL is a file, not a web page. Use moodle_download_file to save it.",
        }
    html = response.text if response is not None else html
    soup = soup_of(html)
    title = soup_text(soup.select_one("h1")) or soup_text(soup.select_one("title"))
    return {
        "url": final,
        "title": title,
        "binary": False,
        "text": html_to_text(html, final),
    }


# --------------------------------------------------------------------------
# Assignment submission
# --------------------------------------------------------------------------
def _parse_form_fields(form) -> dict[str, str]:
    fields: dict[str, str] = {}
    for inp in form.select("input[name]"):
        name = inp.get("name")
        if not name:
            continue
        itype = (inp.get("type") or "text").lower()
        if itype in ("submit", "button", "reset", "file"):
            continue
        if itype in ("checkbox", "radio") and not inp.has_attr("checked"):
            continue
        fields[name] = inp.get("value") or ""
    for ta in form.select("textarea[name]"):
        fields[ta["name"]] = ta.get_text()
    return fields


def _submission_form(soup: BeautifulSoup):
    for form in soup.select("form[id^='mform']"):
        if form.select_one("input[name='files_filemanager']") or form.select_one(
            "textarea[name^='onlinetext_editor']"
        ):
            return form
    return None


def _filemanager_config(html: str) -> dict:
    repo_id = None
    match = re.search(
        r'"id":"(\d+)","name":"[^"]*","type":"upload"', html
    )
    if match:
        repo_id = int(match.group(1))
    itemid = None
    match = re.search(r'"itemid":(\d+)', html)
    if match:
        itemid = int(match.group(1))
    contextid = None
    match = re.search(r'"context":\{"id":(\d+)', html)
    if match:
        contextid = int(match.group(1))
    maxbytes = None
    match = re.search(r'"maxbytes":"(\d+)"', html)
    if match:
        maxbytes = int(match.group(1))
    return {
        "repo_id": repo_id,
        "itemid": itemid,
        "contextid": contextid,
        "maxbytes": maxbytes,
    }


async def _upload_draft_file(
    client: MoodleClient,
    path: str | Path,
    itemid: int,
    repo_id: int,
    contextid: int | None,
    maxbytes: int | None,
) -> dict:
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise MoodleError(f"File not found: {file_path}")
    params = {
        "action": "upload",
        "sesskey": client.sesskey,
        "itemid": itemid,
        "repo_id": repo_id,
        "env": "filemanager",
    }
    if contextid:
        params["ctx_id"] = contextid
    if maxbytes:
        params["maxbytes"] = maxbytes
    data = {
        "title": file_path.name,
        "author": client.user_name or "",
        "license": "allrightsreserved",
        "savepath": "/",
    }
    with file_path.open("rb") as fh:
        response = await client.http.post(
            client.url("/repository/repository_ajax.php"),
            params=params,
            files={
                "repo_upload_file": (
                    file_path.name,
                    fh,
                    "application/octet-stream",
                )
            },
            data=data,
        )
    try:
        payload = response.json()
    except Exception:
        raise MoodleError(f"Upload failed: {response.text[:300]}")
    if isinstance(payload, dict) and payload.get("error"):
        raise MoodleError(f"Upload failed: {payload['error']}")
    return payload


def _find_submit_for_grading_form(soup: BeautifulSoup):
    for form in soup.select("form"):
        action_input = form.select_one("input[name='action']")
        submit_input = form.select_one("input[name='submitbutton']")
        raw = " ".join(
            [
                (action_input.get("value") if action_input else "") or "",
                (submit_input.get("value") if submit_input else "") or "",
            ]
        ).lower()
        if "submit" in raw or "remettre" in raw:
            return form
    return None


async def submit_assignment(
    client: MoodleClient,
    cmid: int,
    text: str | None = None,
    files: list[str] | None = None,
    submit_for_grading: bool = True,
) -> dict:
    """Submit an assignment via Moodle's own submission form.

    Saves the submission first, then (optionally) posts the "Submit for
    grading" form. Returns a structured report including the resulting page.
    """
    files = [f for f in (files or []) if str(f).strip()]
    if not text and not files:
        raise MoodleError("Nothing to submit: provide online text and/or files.")
    edit_html, _edit_url = await client.get_text(
        f"/mod/assign/view.php?id={cmid}&action=editsubmission"
    )
    soup = soup_of(edit_html)
    form = _submission_form(soup)
    if form is None:
        # The assignment may already be submitted, or submissions closed.
        view = await get_assignment(client, cmid)
        raise MoodleError(
            "No submission form is available. The assignment may be closed, "
            f"already submitted, or not accept submissions. Status: {view.get('status', '')[:300]}"
        )

    fields = _parse_form_fields(form)
    action = form.get("action") or f"{client.site}/mod/assign/view.php"
    itemid_raw = fields.get("files_filemanager")
    config = _filemanager_config(edit_html)
    itemid = int(itemid_raw) if itemid_raw and itemid_raw.isdigit() else config.get("itemid")

    uploaded = []
    if files:
        if not itemid:
            raise MoodleError("This assignment does not accept file submissions.")
        if not config.get("repo_id"):
            raise MoodleError("Could not locate the Moodle upload repository.")
        for path in files:
            result = await _upload_draft_file(
                client,
                path,
                itemid,
                config["repo_id"],
                config.get("contextid"),
                config.get("maxbytes"),
            )
            uploaded.append(result)

    if text is not None:
        text_name = "onlinetext_editor[text]"
        if text_name not in fields and not any(
            name.startswith("onlinetext_editor[") for name in fields
        ):
            raise MoodleError("This assignment does not accept online text.")
        import html as html_lib

        paragraphs = "".join(
            f"<p>{html_lib.escape(part).replace(chr(10), '<br>')}</p>"
            for part in text.split("\n\n")
            if part.strip()
        )
        fields[text_name] = paragraphs or "<p></p>"
        fields["onlinetext_editor[format]"] = "1"
        if itemid:
            fields.setdefault("onlinetext_editor[itemid]", str(itemid))

    if form.select_one("input[name='submissionstatement']") is not None:
        fields["submissionstatement"] = "1"
    if fields.get("files_filemanager") is not None and itemid:
        fields["files_filemanager"] = str(itemid)
    fields["submitbutton"] = (
        form.select_one("input[name='submitbutton']").get("value")
        if form.select_one("input[name='submitbutton']")
        else "Save changes"
    )

    response_html, _response_url = await client.post_form(action, fields)
    error = _form_error(response_html)
    if error:
        raise MoodleError(f"Submission was rejected: {error}")

    # Saving may already be final on assignments that do not use drafts.
    saved_view, saved_url = await client.get_text(f"/mod/assign/view.php?id={cmid}")
    saved_status = soup_text(soup_of(saved_view).select_one(".submissionstatustable"))
    final_markers = ("Submitted for grading", "Remis pour évaluation", "Submitted")
    already_submitted = any(marker in saved_status for marker in final_markers)

    result = {
        "ok": True,
        "cmid": cmid,
        "uploaded": uploaded,
        "saved": True,
        "submitted_for_grading": already_submitted,
        "status": saved_status,
        "url": saved_url,
    }
    if already_submitted and not submit_for_grading:
        result["warning"] = (
            "This assignment does not use drafts: saving the submission submitted "
            "it for grading. Remove it from the Moodle web interface if this was a test."
        )

    if submit_for_grading and not already_submitted:
        view_html, _view_url = await client.get_text(f"/mod/assign/view.php?id={cmid}")
        view_soup = soup_of(view_html)
        submit_form = _find_submit_for_grading_form(view_soup)
        if submit_form is None:
            # Already submitted, or the site auto-submits.
            result["submitted_for_grading"] = already_submitted
            result["status"] = soup_text(view_soup.select_one(".submissionstatustable"))
            if not already_submitted:
                result["warning"] = (
                    "Submission saved, but no final 'Submit assignment' form was "
                    "found. Check the submission status in Moodle."
                )
        else:
            submit_fields = _parse_form_fields(submit_form)
            submit_button = submit_form.select_one(
                "input[type='submit'][name], button[type='submit'][name]"
            )
            if submit_button is not None and submit_button.get("name"):
                submit_fields[submit_button["name"]] = (
                    submit_button.get("value")
                    or clean_text(submit_button.get_text(" ", strip=True))
                )
            submit_action = submit_form.get("action") or f"{client.site}/mod/assign/view.php"
            submit_html, submit_url = await client.post_form(submit_action, submit_fields)
            error = _form_error(submit_html)
            if error:
                raise MoodleError(f"Submit-for-grading was rejected: {error}")
            # A confirmation page may require a second POST.
            confirm_form = _find_confirm_form(submit_html)
            if confirm_form is not None:
                confirm_fields = _parse_form_fields(confirm_form)
                confirm_button = confirm_form.select_one(
                    "input[type='submit'][name], button[type='submit'][name]"
                )
                if confirm_button is not None and confirm_button.get("name"):
                    confirm_fields[confirm_button["name"]] = (
                        confirm_button.get("value")
                        or clean_text(confirm_button.get_text(" ", strip=True))
                    )
                confirm_action = confirm_form.get("action") or submit_action
                submit_html, submit_url = await client.post_form(
                    confirm_action, confirm_fields
                )
            result["submitted_for_grading"] = True
            result["status"] = soup_text(
                soup_of(submit_html).select_one(".submissionstatustable")
            )
            result["url"] = submit_url

    return result


def _form_error(html: str) -> str:
    soup = soup_of(html)
    for selector in (".alert-danger", ".invalid-feedback", ".error"):
        for node in soup.select(selector):
            text = clean_text(node.get_text(" ", strip=True))
            if text:
                return text
    return ""


def _find_confirm_form(html: str):
    soup = soup_of(html)
    for form in soup.select("form"):
        if form.select_one("input[name='confirm']") or form.select_one(
            "button[name='confirm']"
        ):
            return form
    return None


async def remove_submission(client: MoodleClient, cmid: int) -> dict:
    """Remove the current user's submission (Moodle confirmation + POST)."""
    confirm_html, _confirm_url = await client.get_text(
        f"/mod/assign/view.php?id={cmid}&action=removesubmissionconfirm"
    )
    soup = soup_of(confirm_html)
    form = None
    for candidate in soup.select("form"):
        action_input = candidate.select_one("input[name='action']")
        if action_input and (action_input.get("value") or "") == "removesubmission":
            form = candidate
            break
    if form is None:
        raise MoodleError(
            "Moodle did not offer a 'remove submission' form. The submission "
            "may be locked, graded, or already removed."
        )
    fields = _parse_form_fields(form)
    remove_button = form.select_one(
        "input[type='submit'][name], button[type='submit'][name]"
    )
    if remove_button is not None and remove_button.get("name"):
        fields[remove_button["name"]] = (
            remove_button.get("value")
            or clean_text(remove_button.get_text(" ", strip=True))
        )
    action = form.get("action") or f"{client.site}/mod/assign/view.php"
    html, url = await client.post_form(action, fields)
    error = _form_error(html)
    if error:
        raise MoodleError(f"Removal was rejected: {error}")
    view = await get_assignment(client, cmid)
    return {
        "ok": True,
        "cmid": cmid,
        "url": url,
        "status": view.get("status", ""),
        "can_edit": view.get("can_edit", False),
    }
