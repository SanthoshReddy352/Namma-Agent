"""Phase 4b live-hunt fixes: follow-up turns see what earlier turns really did
(the ``[actions: …]`` record), and convert_document makes spreadsheets."""
import csv
import zipfile

from namma_agent.core.memory import Database, action_record
from namma_agent.tools import convert


def _steps():
    return [
        {"kind": "thinking", "text": "plan"},
        {"kind": "tool", "tool": "update_todos", "args": {"todos": []}, "state": "ok"},
        {"kind": "tool", "tool": "make_dir", "args": {"path": "C:/w/trip-plan"},
         "state": "ok", "summary": "created"},
        {"kind": "tool", "tool": "write_file",
         "args": {"path": "C:/w/trip-plan/packing.md", "content": "x" * 5000},
         "state": "ok", "summary": "wrote 5000 chars"},
        {"kind": "tool", "tool": "run_shell", "args": {"command": "bad"},
         "state": "fail", "summary": "exit 1"},
    ]


def test_action_record_lists_real_actions_compactly():
    rec = action_record(_steps())
    assert rec.startswith("[actions:")
    assert "write_file(path=C:/w/trip-plan/packing.md) → ok: wrote 5000 chars" in rec
    assert "make_dir(path=C:/w/trip-plan) → ok" in rec
    assert "run_shell(command=bad) → fail: exit 1" in rec
    assert "update_todos" not in rec          # bookkeeping is skipped
    assert "xxxx" not in rec                  # file content never enters history
    assert action_record([{"kind": "thinking", "text": "x"}]) == ""


def test_action_record_is_capped():
    steps = [{"kind": "tool", "tool": "read_file", "args": {"path": f"f{i}"}, "state": "ok"}
             for i in range(30)]
    assert action_record(steps).count("\n- ") == 13      # 12 entries + the ellipsis


def test_history_carries_actions_only_when_asked(tmp_path):
    db = Database(str(tmp_path / "m.db"))
    sid = db.create_session("t") if hasattr(db, "create_session") else "s1"
    db.add_turn(sid, "user", "make a trip folder")
    db.add_turn(sid, "assistant", "Created trip-plan.", ["make_dir"], meta={"steps": _steps()})
    plain = db.recent_turns(sid, 10)
    assert plain[-1]["content"] == "Created trip-plan."
    rich = db.recent_turns(sid, 10, with_actions=True)
    assert rich[-1]["content"].startswith("Created trip-plan.\n\n[actions:")
    assert "packing.md" in rich[-1]["content"]
    assert rich[0]["content"] == "make a trip folder"     # user turns untouched


MD = """# Weather

## Temperatures
| Day | Temp | Rain (mm) |
|---|---|---|
| Mon | 31C | 1,200 |
| **Tue** | 33C | 0.5 |

## Notes
| Note |
|---|
| sunny |
"""


def _convert(tmp_path, monkeypatch, to):
    monkeypatch.setattr(convert, "_OUT_DIR", tmp_path)
    res = convert._convert({"content": MD, "to": to})
    assert res.ok, res.error
    assert res.data["format"] in ("xlsx", "csv")
    return next(tmp_path.glob(f"*.{res.data['format']}"))


def test_xlsx_one_sheet_per_table_with_typed_numbers(tmp_path, monkeypatch):
    out = _convert(tmp_path, monkeypatch, "excel")
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert {"xl/workbook.xml", "xl/worksheets/sheet1.xml",
                "xl/worksheets/sheet2.xml", "[Content_Types].xml"} <= names
        wb = z.read("xl/workbook.xml").decode()
        assert 'name="Temperatures"' in wb and 'name="Notes"' in wb
        s1 = z.read("xl/worksheets/sheet1.xml").decode()
    assert "<v>1200</v>" in s1 and "<v>0.5</v>" in s1     # numbers typed
    assert ">31C<" in s1                                   # text stays text
    assert ">Tue<" in s1 and "**" not in s1                # inline md stripped


def test_csv_and_missing_table_error(tmp_path, monkeypatch):
    out = _convert(tmp_path, monkeypatch, "csv")
    rows = list(csv.reader(out.open(encoding="utf-8-sig")))
    assert rows[0] == ["Day", "Temp", "Rain (mm)"] and rows[1][0] == "Mon"
    assert ["Note"] in rows
    res = convert._convert({"content": "just text", "to": "xlsx"})
    assert not res.ok and "Markdown table" in res.error


def test_reminders_live_in_the_data_dir(tmp_path, monkeypatch):
    """Reminders follow NAMMA_DATA_DIR (they used to be pinned to <repo>/data, so
    a scratch run's reminders fired in the owner's real app)."""
    from namma_agent.tools import scheduler

    monkeypatch.setenv("NAMMA_DATA_DIR", str(tmp_path))
    assert scheduler._store_path() == tmp_path / "reminders.json"
