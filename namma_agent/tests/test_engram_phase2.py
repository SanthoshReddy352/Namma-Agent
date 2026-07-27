"""Phase 2 — the Memory tab + Settings run on Engram (docs/MEMORY_SYSTEM_DESIGN.md §9/§12).

Offline: scripted providers, in-memory SQLite, filesystem probes pointed at tmp
dirs. Covers the service-level memory surface the new /api/memory/* routes call,
the consolidation duplicate-merge, and environment tool discovery (the "tesseract
is installed but not on PATH" fix).
"""
from __future__ import annotations


import pytest

from namma_agent.core.engram import environment as envmod
from namma_agent.core.engram.store import EngramStore
from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry
from namma_agent.service import NammaAgentService


class Echo(Provider):
    name = "echo"

    def __init__(self):
        super().__init__(model="echo")

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        return LLMResponse(content="[]")


@pytest.fixture
def svc():
    return NammaAgentService(config={"database": {"path": ":memory:"}},
                             provider=Echo(), registry=ToolRegistry())


# ── service memory surface (what /api/memory/* calls) ────────────────────────

def test_memory_status_native_always_on(svc):
    st = svc.memory_status()
    assert st["connected"] is True and st["engine"] == "engram"
    assert {"items", "entities", "relations"} <= set(st)


def test_memory_graph_maps_store_shape(svc):
    iid = svc.engram.store.add_item("Santhosh studies at KARE", subject="santhosh",
                                    predicate="studies_at", object="KARE")
    svc.engram.store.add_relation("santhosh", "studies_at", "KARE", item_id=iid)
    g = svc.memory_graph()
    assert g["ok"] and g["counts"]["nodes"] == 2 and g["counts"]["edges"] == 1
    assert {n["label"] for n in g["nodes"]} == {"santhosh", "KARE"}
    edge = g["edges"][0]
    assert edge["relation"] == "studies at" and not edge["expired"]


def test_memory_recall_items_and_forget(svc):
    svc.engram.store.add_item("The user loves Python")
    r = svc.memory_recall("python")
    assert r["ok"] and any("Python" in x["text"] for x in r["results"])
    items = svc.memory_items()
    assert items["ok"] and len(items["items"]) == 1
    out = svc.memory_forget(query="python")
    assert out["ok"] and out["forgot"] == 1
    assert svc.memory_items()["items"] == []          # live view is empty
    assert svc.memory_items(include_expired=True)["items"]  # history remains


def test_memory_forget_everything_wipes(svc):
    svc.engram.store.add_item("a fact")
    svc.engram.core.add("user", "Name is Santhosh")
    out = svc.memory_forget(everything=True)
    assert out["ok"]
    assert svc.memory_items(include_expired=True)["items"] == []
    assert svc.memory_core()["user"]["entries"] == []


def test_memory_core_edit_by_entry_id(svc):
    assert svc.memory_core_save("user", "add", text="Prefers dark mode")["ok"]
    entry = svc.memory_core()["user"]["entries"][0]
    assert svc.memory_core_save("user", "replace", text="Prefers light mode",
                                entry_id=entry["id"])["ok"]
    texts = [e["text"] for e in svc.memory_core()["user"]["entries"]]
    assert texts == ["Prefers light mode"]
    assert svc.memory_core_save("user", "remove", entry_id=entry["id"])["ok"]
    assert svc.memory_core()["user"]["entries"] == []


def test_memory_remember_queues_pipeline(svc):
    seen = []
    svc.engram.writer.ingest_text = lambda text, source="manual": seen.append((text, source))
    out = svc.memory_remember("I am building Namma Agent")
    assert out["ok"] and out["queued"] and seen[0][1] == "manual"


def test_memory_consolidate_reports_and_updates_status(svc):
    # two exact-duplicate live facts → one merged away
    svc.engram.store.add_item("The user loves Python")
    svc.engram.store.add_item("the user loves python")
    out = svc.memory_consolidate()
    assert out["ok"] and out["merged"] == 1
    assert svc.memory_status()["last_consolidation"]["merged"] == 1
    assert len(svc.memory_items()["items"]) == 1


def test_memory_settings_roundtrip(svc, monkeypatch, tmp_path):
    import namma_agent.config as cfg
    monkeypatch.setattr(cfg, "_config_path", lambda: tmp_path / "config.yaml")
    s = svc.memory_settings()
    assert s["ok"] and s["engine"] == "engram" and s["prefetch"] is True
    out = svc.save_memory_settings({"prefetch": False, "k": 3,
                                    "salience_min_chars": 40, "budget_per_hour": 10})
    assert out["prefetch"] is False and out["k"] == 3
    assert svc.engram.prefetch_enabled is False and svc.engram.prefetch_k == 3
    assert svc.engram.writer.min_chars == 40
    assert svc.engram.writer.budget_per_hour == 10
    # persisted to config.local.yaml under memory.*
    local = (tmp_path / "config.local.yaml").read_text(encoding="utf-8")
    assert "prefetch: false" in local and "salience_min_chars: 40" in local


def test_memory_environment_endpoint(svc):
    out = svc.memory_environment()
    assert out["ok"] and out["environment"]["home"]
    assert "HOST" in out["rendered"]


# ── consolidation: duplicate merge keeps history ─────────────────────────────

def test_merge_exact_duplicates_sums_frequency():
    store = EngramStore(Database(":memory:"))
    a = store.add_item("The user drinks filter coffee")
    b = store.add_item("the user drinks   filter coffee")
    merged = store.merge_exact_duplicates()
    assert merged == 1
    live = store.list_items()
    assert len(live) == 1 and live[0]["frequency"] == 2
    gone = [i for i in store.list_items(include_expired=True) if i["expired_at"]]
    assert gone and gone[0]["superseded_by"] == live[0]["id"]
    assert {a, b} == {live[0]["id"], gone[0]["id"]}


def test_hard_delete_gc_orphan_entities():
    """Hard-deleting a fact must not leave floating entity nodes in the graph."""
    store = EngramStore(Database(":memory:"))
    a = store.add_item("user loves Python", subject="user", predicate="loves",
                       object="Python")
    store.add_relation("user", "loves", "Python", item_id=a)
    b = store.add_item("user builds Namma", subject="user", predicate="builds",
                       object="Namma")
    store.add_relation("user", "builds", "Namma", item_id=b)

    store.hard_delete(a)
    g = store.graph()
    assert {n["name"] for n in g["nodes"]} == {"user", "Namma"}  # shared node stays
    assert len(g["edges"]) == 1

    store.hard_delete(b)
    g = store.graph()
    assert g["nodes"] == [] and g["edges"] == []


# ── environment: installed-tool discovery ────────────────────────────────────

def test_discover_tools_finds_off_path_binary(monkeypatch, tmp_path):
    """A tesseract that lives in an install dir (not on PATH) is FOUND — the
    exact failure mode this fixes: the agent declaring a tool missing after one
    PATH miss."""
    root = tmp_path / "Program Files"
    exe = root / "Tesseract-OCR" / "tesseract.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(envmod.shutil, "which", lambda name: None)
    monkeypatch.setattr(envmod, "_install_roots", lambda: [root])
    monkeypatch.setattr(envmod.platform, "system", lambda: "Windows")
    found = envmod.discover_tools(("tesseract",))
    assert found == {"tesseract": str(exe)}
    assert envmod.find_binary("tesseract") == str(exe)


def test_find_binary_prefers_cached_env(monkeypatch, tmp_path):
    exe = tmp_path / "ffmpeg.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(envmod.shutil, "which", lambda name: None)
    monkeypatch.setattr(envmod, "_install_roots", lambda: [])
    assert envmod.find_binary("ffmpeg", env={"tools": {"ffmpeg": str(exe)}}) == str(exe)
    # a stale cache entry (file gone) falls through instead of being trusted
    assert envmod.find_binary("ffmpeg", env={"tools": {"ffmpeg": str(tmp_path / 'gone.exe')}}) is None


def test_render_lists_installed_tools(monkeypatch, tmp_path):
    mem = envmod.EnvironmentMemory(data_dir=None)
    exe = tmp_path / "Tools" / "tesseract.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    mem._env = envmod.probe()
    mem._env["tools"] = {"tesseract": str(exe)}
    block = mem.render()
    assert "Installed tools:" in block and str(exe) in block
    assert "Before saying a program is missing" in block
