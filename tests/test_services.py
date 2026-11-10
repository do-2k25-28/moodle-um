from bs4 import BeautifulSoup

from moodle_um.services import (
    _filemanager_config,
    _form_error,
    _header_index,
    _parse_activity,
    _parse_form_fields,
    _submission_form,
)


def test_header_index_handles_french_and_english_headers():
    headers = ["Section", "Devoirs", "Date limite", "Travail remis", "Note"]
    assert _header_index(headers) == {"due": 2, "submission": 3, "grade": 4}

    english = ["Section", "Assignment", "Due date", "Submission status", "Grade"]
    assert _header_index(english) == {"due": 2, "submission": 3, "grade": 4}


def test_parse_activity_extracts_cmid_modname_and_url():
    html = """
    <li class="activity activity-wrapper assign" data-id="778745" data-modname="assign">
      <div class="activity-item" data-activityname="Rapport">
        <a class="aalink" href="https://moodle.example/mod/assign/view.php?id=778745">
          <span class="instancename">Rapport Devoir</span>
        </a>
        <div class="activity-dates">À rendre : demain</div>
      </div>
    </li>
    """
    li = BeautifulSoup(html, "lxml").select_one("li.activity")
    activity = _parse_activity(li, "https://moodle.example/course/view.php?id=1")
    assert activity["cmid"] == 778745
    assert activity["modname"] == "assign"
    assert activity["name"] == "Rapport"
    assert activity["url"].endswith("/mod/assign/view.php?id=778745")
    assert "demain" in activity["dates"]


def test_filemanager_config_reads_upload_repository():
    html = """
    "repositories":{"3":{"id":"3","name":"Upload a file","type":"upload"}},
    "itemid":194981003,
    "context":{"id":3275119},
    "maxbytes":"104857600"
    """
    config = _filemanager_config(html)
    assert config == {
        "repo_id": 3,
        "itemid": 194981003,
        "contextid": 3275119,
        "maxbytes": 104857600,
    }


def test_submission_form_and_fields():
    html = """
    <form id="mform1_x" action="https://moodle.example/mod/assign/view.php">
      <input type="hidden" name="id" value="1161051">
      <input type="hidden" name="action" value="savesubmission">
      <input type="hidden" name="files_filemanager" value="123">
      <input type="checkbox" name="submissionstatement" value="1">
      <input type="submit" name="submitbutton" value="Save changes">
      <textarea name="onlinetext_editor[text]">hello</textarea>
    </form>
    """
    soup = BeautifulSoup(html, "lxml")
    form = _submission_form(soup)
    assert form is not None
    fields = _parse_form_fields(form)
    assert fields["id"] == "1161051"
    assert fields["files_filemanager"] == "123"
    assert "submissionstatement" not in fields  # unchecked checkboxes are skipped
    assert fields["onlinetext_editor[text]"] == "hello"
    assert "submitbutton" not in fields  # submit buttons are added explicitly


def test_form_error_detects_danger_alert():
    html = '<div class="alert alert-danger">You are required to agree</div>'
    assert "required" in _form_error(html)


def test_form_error_ignores_success_alert():
    html = '<div class="alert alert-success">Saved</div>'
    assert _form_error(html) == ""
