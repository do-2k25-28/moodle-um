from moodle_um.client import extract_moodle_cfg
from moodle_um.parsers import find_course_links, html_to_text


def test_extract_moodle_cfg_handles_nested_objects_and_braces_in_strings():
    html = """
    <script>
    M.cfg = {"wwwroot":"https://moodle.example","sesskey":"abc123",
             "userId":42,"homeurl":{},"note":"a } in a string"};
    </script>
    """
    cfg = extract_moodle_cfg(html)
    assert cfg["sesskey"] == "abc123"
    assert cfg["userId"] == 42
    assert cfg["note"] == "a } in a string"


def test_extract_moodle_cfg_returns_empty_when_absent():
    assert extract_moodle_cfg("<html></html>") == {}


def test_html_to_text_removes_scripts_and_keeps_content():
    html = """
    <html><body>
      <nav>menu</nav>
      <main id="region-main">
        <h1>Cours</h1>
        <p>Bonjour <strong>tout le monde</strong>.</p>
        <script>alert(1)</script>
      </main>
    </body></html>
    """
    text = html_to_text(html, "https://moodle.example/course/view.php?id=1")
    assert "Cours" in text
    assert "Bonjour" in text
    assert "alert" not in text
    assert "menu" not in text


def test_find_course_links_deduplicates_and_skips_site_home():
    html = """
    <div>
      <a href="/course/view.php?id=10">Algo</a>
      <a href="https://moodle.example/course/view.php?id=10">Algo (again)</a>
      <a href="/course/view.php?id=1">Home</a>
      <a href="/course/view.php?id=20">Réseaux</a>
    </div>
    """
    courses = find_course_links(html, "https://moodle.example/my/")
    assert [c["id"] for c in courses] == [10, 20]
    assert courses[0]["name"] == "Algo"
