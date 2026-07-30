"""System resource monitor — CPU, RAM, disk, network, top processes.

Pure stdlib, cross-platform (Windows + Linux/macOS). No external deps.

Tools:
  system_monitor       — snapshot of CPU, RAM, disk, network, top processes
  system_monitor_trend — resource usage over time (stores snapshots, shows trend)
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from typing import Any

from namma_agent.core.tools import ToolRegistry, ToolResult

# In-memory ring buffer for trend data (max 60 snapshots = ~1 hour at 1-min intervals)
_MAX_SNAPSHOTS = 60
_snapshots: list[dict[str, Any]] = []


def _safe_int(val: Any, default: int = 0) -> int:
    """Safely convert a value to int, handling None."""
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _get_cpu_usage() -> dict:
    """Get CPU info — load average on Unix, usage on Windows."""
    info: dict[str, Any] = {}
    try:
        info["count"] = os.cpu_count() or 1
    except Exception:
        info["count"] = "unknown"

    if platform.system() == "Windows":
        try:
            proc = subprocess.run(
                ["powershell", "-Command",
                 "(Get-CimInstance Win32_Processor).LoadPercentage"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=10,
            )
            load = (proc.stdout or "").strip().split("\n")[0].strip()
            info["usage_percent"] = float(load) if load else None
        except Exception:
            info["usage_percent"] = None
        info["load_avg"] = None
    else:
        try:
            la1, la5, la15 = os.getloadavg()
            info["load_avg"] = {"1m": round(la1, 2), "5m": round(la5, 2), "15m": round(la15, 2)}
            info["usage_percent"] = round(la1 / info["count"] * 100, 1)
        except OSError:
            info["load_avg"] = None
            info["usage_percent"] = None

    return info


def _get_memory() -> dict:
    """Get memory usage — /proc/meminfo on Linux, WMI on Windows."""
    info: dict[str, Any] = {}

    if platform.system() == "Windows":
        try:
            proc = subprocess.run(
                ["powershell", "-Command",
                 "$m = (Get-CimInstance Win32_OperatingSystem); "
                 "Write-Host $m.TotalVisibleMemorySize; "
                 "Write-Host $m.FreePhysicalMemory"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=10,
            )
            lines = (proc.stdout or "").strip().split("\n")
            total_kb = int(lines[0].strip()) if len(lines) > 0 else 0
            free_kb = int(lines[1].strip()) if len(lines) > 1 else 0
            used_kb = total_kb - free_kb
            info = {
                "total_gb": round(total_kb / 1048576, 2),
                "used_gb": round(used_kb / 1048576, 2),
                "free_gb": round(free_kb / 1048576, 2),
                "usage_percent": round(used_kb / total_kb * 100, 1) if total_kb else 0,
            }
        except Exception:
            info = {"error": "could not read memory"}
    else:
        try:
            mem = {}
            with open("/proc/meminfo") as fh:
                for line in fh:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = int(parts[1].strip().split()[0])
                        mem[key] = val
            total = mem.get("MemTotal", 0)
            avail = mem.get("MemAvailable", mem.get("MemFree", 0))
            used = total - avail
            info = {
                "total_gb": round(total / 1048576, 2),
                "used_gb": round(used / 1048576, 2),
                "free_gb": round(avail / 1048576, 2),
                "usage_percent": round(used / total * 100, 1) if total else 0,
                "swap_total_gb": round(mem.get("SwapTotal", 0) / 1048576, 2),
                "swap_used_gb": round(
                    (mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)) / 1048576, 2
                ),
            }
        except Exception:
            info = {"error": "could not read /proc/meminfo"}

    return info


def _get_disk() -> list[dict]:
    """Get disk usage for all mounted drives."""
    disks = []
    if platform.system() == "Windows":
        for letter in "CDEFGHIJKLMNOP":
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                try:
                    total, used, free = shutil.disk_usage(drive)
                    disks.append({
                        "mount": drive,
                        "total_gb": round(total / 1e9, 1),
                        "used_gb": round(used / 1e9, 1),
                        "free_gb": round(free / 1e9, 1),
                        "usage_percent": round(used / total * 100, 1),
                    })
                except Exception:
                    pass
    else:
        try:
            proc = subprocess.run(
                ["df", "-h", "--output=source,size,used,avail,pcent,target"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=5,
            )
            for line in (proc.stdout or "").strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) >= 6 and not parts[0].startswith("tmpfs"):
                    disks.append({
                        "mount": parts[5],
                        "total_gb": parts[1],
                        "used_gb": parts[2],
                        "free_gb": parts[3],
                        "usage_percent": parts[4],
                    })
        except Exception:
            try:
                total, used, free = shutil.disk_usage("/")
                disks.append({
                    "mount": "/",
                    "total_gb": round(total / 1e9, 1),
                    "used_gb": round(used / 1e9, 1),
                    "free_gb": round(free / 1e9, 1),
                    "usage_percent": round(used / total * 100, 1),
                })
            except Exception:
                pass

    return disks


def _get_network() -> dict:
    """Get network I/O stats."""
    info: dict[str, Any] = {}

    if platform.system() == "Windows":
        try:
            proc = subprocess.run(
                ["powershell", "-Command",
                 "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | "
                 "Select-Object Name,LinkSpeed,ReceivedBytes,SentBytes | "
                 "ConvertTo-Json"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=10,
            )
            import json
            adapters = json.loads(proc.stdout or "[]")
            if not isinstance(adapters, list):
                adapters = [adapters]
            interfaces = []
            for a in adapters:
                interfaces.append({
                    "name": a.get("Name", "unknown"),
                    "speed": a.get("LinkSpeed", "unknown"),
                    "rx_bytes": _safe_int(a.get("ReceivedBytes")),
                    "tx_bytes": _safe_int(a.get("SentBytes")),
                })
            info["interfaces"] = interfaces
        except Exception:
            info = {"error": "could not read network stats"}
    else:
        try:
            interfaces = []
            with open("/proc/net/dev") as fh:
                for line in fh:
                    if ":" not in line:
                        continue
                    name, data = line.split(":", 1)
                    name = name.strip()
                    if name == "lo":
                        continue
                    vals = data.split()
                    if len(vals) >= 10:
                        interfaces.append({
                            "name": name,
                            "rx_bytes": int(vals[0]),
                            "tx_bytes": int(vals[8]),
                            "rx_packets": int(vals[1]),
                            "tx_packets": int(vals[9]),
                        })
            info["interfaces"] = interfaces
        except Exception:
            info = {"error": "could not read /proc/net/dev"}

    return info


def _get_top_processes(count: int = 5) -> list[dict]:
    """Get top processes by CPU/memory usage."""
    procs = []
    try:
        if platform.system() == "Windows":
            proc = subprocess.run(
                ["powershell", "-Command",
                 "Get-Process | Sort-Object CPU -Descending | "
                 f"Select-Object -First {count} Name,Id,CPU,"
                 "@{N='MemMB';E={[math]::Round($_.WorkingSet64/1MB,1)}} | "
                 "ConvertTo-Json"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=10,
            )
            import json
            data = json.loads(proc.stdout or "[]")
            if not isinstance(data, list):
                data = [data]
            for p in data:
                procs.append({
                    "name": p.get("Name", "?"),
                    "pid": p.get("Id", "?"),
                    "cpu_sec": round(p.get("CPU", 0) or 0, 1),
                    "mem_mb": p.get("MemMB", 0) or 0,
                })
        else:
            proc = subprocess.run(
                ["ps", "aux", "--sort=-pcpu"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=5,
            )
            lines = (proc.stdout or "").strip().split("\n")[1 : count + 1]
            for line in lines:
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    procs.append({
                        "name": parts[10][:40],
                        "pid": parts[1],
                        "cpu_percent": float(parts[2]),
                        "mem_percent": float(parts[3]),
                    })
    except Exception:
        pass
    return procs


def _take_snapshot() -> dict:
    """Take a full system snapshot."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    snap = {
        "timestamp": ts,
        "cpu": _get_cpu_usage(),
        "memory": _get_memory(),
        "disks": _get_disk(),
        "network": _get_network(),
        "top_processes": _get_top_processes(5),
    }
    return snap


def _format_snapshot(snap: dict) -> str:
    """Format a snapshot into readable text."""
    lines = [f"System Monitor — {snap['timestamp']}\n"]

    # CPU
    cpu = snap.get("cpu", {})
    usage = cpu.get("usage_percent")
    lines.append("CPU:")
    lines.append(f"  Cores: {cpu.get('count', '?')}")
    if usage is not None:
        bar_len = int(usage / 5)
        bar = "#" * bar_len + "-" * (20 - bar_len)
        lines.append(f"  Usage: [{bar}] {usage}%")
    if cpu.get("load_avg"):
        la = cpu["load_avg"]
        lines.append(f"  Load:  {la['1m']} (1m) / {la['5m']} (5m) / {la['15m']} (15m)")

    # Memory
    mem = snap.get("memory", {})
    if "error" not in mem:
        usage_m = mem.get("usage_percent", 0)
        bar_len = int(usage_m / 5)
        bar = "#" * bar_len + "-" * (20 - bar_len)
        lines.append(f"\nMemory:")
        lines.append(f"  Usage: [{bar}] {usage_m}%")
        lines.append(
            f"  Used:  {mem.get('used_gb', '?')} GB / {mem.get('total_gb', '?')} GB "
            f"(free: {mem.get('free_gb', '?')} GB)"
        )
        if mem.get("swap_total_gb", 0) > 0:
            lines.append(
                f"  Swap:  {mem.get('swap_used_gb', 0)} GB / {mem.get('swap_total_gb', 0)} GB"
            )

    # Disks
    disks = snap.get("disks", [])
    if disks:
        lines.append("\nDisks:")
        for d in disks:
            lines.append(
                f"  {d['mount']:12s}  {d.get('used_gb', '?'):>6} / {d.get('total_gb', '?')} GB "
                f"({d.get('usage_percent', '?')})"
            )

    # Network
    net = snap.get("network", {})
    ifaces = net.get("interfaces", [])
    if ifaces:
        lines.append("\nNetwork:")
        for iface in ifaces:
            rx = iface.get("rx_bytes", 0) or 0
            tx = iface.get("tx_bytes", 0) or 0
            rx_mb = round(rx / 1048576, 1)
            tx_mb = round(tx / 1048576, 1)
            speed = iface.get("speed", "")
            lines.append(f"  {iface['name']:12s}  RX: {rx_mb} MB  TX: {tx_mb} MB  {speed}")

    # Top processes
    procs = snap.get("top_processes", [])
    if procs:
        lines.append("\nTop Processes:")
        for p in procs:
            cpu_info = ""
            if "cpu_percent" in p:
                cpu_info = f"CPU: {p['cpu_percent']}%"
            elif "cpu_sec" in p:
                cpu_info = f"CPU: {p['cpu_sec']}s"
            mem_info = ""
            if "mem_percent" in p:
                mem_info = f"MEM: {p['mem_percent']}%"
            elif "mem_mb" in p:
                mem_info = f"MEM: {p['mem_mb']} MB"
            lines.append(f"  {p['name'][:25]:25s}  PID: {str(p.get('pid', '?')):>7}  {cpu_info:12s}  {mem_info}")

    return "\n".join(lines)


def _system_monitor(args: dict) -> ToolResult:
    """Take a system resource snapshot."""
    snap = _take_snapshot()
    text = _format_snapshot(snap)
    return ToolResult(ok=True, content=text, data=snap)


def _system_monitor_trend(args: dict) -> ToolResult:
    """Show resource usage trend over time."""
    global _snapshots

    action = (args.get("action") or "status").lower()

    if action == "snapshot":
        snap = _take_snapshot()
        _snapshots.append(snap)
        if len(_snapshots) > _MAX_SNAPSHOTS:
            _snapshots = _snapshots[-_MAX_SNAPSHOTS:]
        return ToolResult(
            ok=True,
            content=f"Snapshot saved ({len(_snapshots)}/{_MAX_SNAPSHOTS}).",
            data={"snapshots_count": len(_snapshots), "latest": snap},
        )

    if action == "clear":
        _snapshots = []
        return ToolResult(ok=True, content="Trend data cleared.")

    # status: show the trend
    if not _snapshots:
        snap = _take_snapshot()
        _snapshots.append(snap)
        return ToolResult(
            ok=True,
            content=(
                "No trend data yet. Taking an initial snapshot.\n"
                "Use action='snapshot' to record periodic samples, then action='status' to see the trend.\n\n"
                + _format_snapshot(snap)
            ),
            data={"snapshots_count": 1},
        )

    # Build trend summary
    lines = [f"System Trend ({len(_snapshots)} snapshots, last: {_snapshots[-1]['timestamp']})\n"]

    # CPU trend
    cpu_vals = [s["cpu"].get("usage_percent", 0) for s in _snapshots if s["cpu"].get("usage_percent") is not None]
    if cpu_vals:
        lines.append(f"CPU:    min={min(cpu_vals)}%  max={max(cpu_vals)}%  avg={round(sum(cpu_vals)/len(cpu_vals), 1)}%")

    # Memory trend
    mem_vals = [s["memory"].get("usage_percent", 0) for s in _snapshots if "error" not in s.get("memory", {})]
    if mem_vals:
        lines.append(f"Memory: min={min(mem_vals)}%  max={max(mem_vals)}%  avg={round(sum(mem_vals)/len(mem_vals), 1)}%")

    # Disk (last snapshot)
    last_disks = _snapshots[-1].get("disks", [])
    if last_disks:
        lines.append("\nDisk (current):")
        for d in last_disks:
            lines.append(f"  {d['mount']:12s}  {d.get('used_gb', '?')} / {d.get('total_gb', '?')} GB ({d.get('usage_percent', '?')})")

    # Network delta — safely handle None values
    if len(_snapshots) >= 2:
        prev_net = _snapshots[-2].get("network", {})
        curr_net = _snapshots[-1].get("network", {})
        prev_ifaces = {i["name"]: i for i in prev_net.get("interfaces", [])}
        curr_ifaces = {i["name"]: i for i in curr_net.get("interfaces", [])}
        lines.append("\nNetwork Delta (since last snapshot):")
        for name, curr in curr_ifaces.items():
            prev = prev_ifaces.get(name, {})
            rx_curr = _safe_int(curr.get("rx_bytes"))
            rx_prev = _safe_int(prev.get("rx_bytes"))
            tx_curr = _safe_int(curr.get("tx_bytes"))
            tx_prev = _safe_int(prev.get("tx_bytes"))
            rx_delta = rx_curr - rx_prev
            tx_delta = tx_curr - tx_prev
            lines.append(
                f"  {name:12s}  RX: +{round(rx_delta/1048576, 2)} MB  TX: +{round(tx_delta/1048576, 2)} MB"
            )

    # Latest snapshot detail
    lines.append("\n--- Latest Snapshot ---")
    lines.append(_format_snapshot(_snapshots[-1]))

    return ToolResult(ok=True, content="\n".join(lines), data={"snapshots_count": len(_snapshots)})


def register(registry: ToolRegistry) -> None:
    registry.register(
        "system_monitor",
        "Get a real-time snapshot of CPU, RAM, disk usage, network I/O, and top processes.",
        {
            "type": "object",
            "properties": {},
        },
        _system_monitor,
    )

    registry.register(
        "system_monitor_trend",
        "Track system resource usage over time. Use action='snapshot' to record samples, action='status' to see the trend, action='clear' to reset.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "snapshot", "clear"],
                    "description": "status (default): show trend; snapshot: record current state; clear: reset",
                },
            },
        },
        _system_monitor_trend,
    )
