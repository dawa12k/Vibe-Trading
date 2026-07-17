"""Backtest execution tool: validates config.json + signal_engine.py and runs the built-in engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backtest.loaders.registry import VALID_SOURCES
from src.agent.progress import emit_progress
from src.agent.tools import BaseTool
from src.core.runner import Runner
from src.tools.path_utils import safe_run_dir


def _is_confirmed(value: Any) -> bool:
    """Return True only when the caller explicitly approved the backtest."""
    if value is True:
        return True
    if isinstance(value, str) and value.strip().lower() in {"true", "yes", "1"}:
        return True
    return False


def _config_preview(run_path: Path) -> dict[str, Any]:
    """Build a short config summary for the confirmation prompt."""
    config_path = run_path / "config.json"
    if not config_path.exists():
        return {"warning": "config.json not found yet"}
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"warning": f"config.json parse error: {exc}"}
    keys = (
        "source",
        "codes",
        "start_date",
        "end_date",
        "interval",
        "initial_cash",
        "benchmark",
    )
    preview = {key: config[key] for key in keys if key in config}
    signal_path = run_path / "code" / "signal_engine.py"
    preview["signal_engine"] = "present" if signal_path.exists() else "missing"
    return preview


def backtest_needs_confirmation(run_dir: str) -> str:
    """Return a needs_confirmation payload without starting the engine."""
    preview: dict[str, Any]
    try:
        run_path = safe_run_dir(run_dir)
        preview = _config_preview(run_path)
    except ValueError as exc:
        preview = {"warning": str(exc)}
    return json.dumps(
        {
            "status": "needs_confirmation",
            "error": (
                "Backtest not started. Ask the user to confirm this run, then call "
                "backtest again with confirmed=true only after they approve."
            ),
            "run_dir": run_dir,
            "preview": preview,
            "next_step": (
                "Show the user the preview (source, codes, dates). If they approve, "
                "re-call backtest(run_dir=..., confirmed=true)."
            ),
        },
        ensure_ascii=False,
    )


def run_backtest(run_dir: str) -> str:
    """Run backtest: validate config.json + signal_engine.py, invoke built-in engine.

    Args:
        run_dir: Path to the run directory.

    Returns:
        JSON-formatted execution result.
    """
    emit_progress("validate", message="validating run_dir and config")
    try:
        run_path = safe_run_dir(run_dir)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

    config_path = run_path / "config.json"
    if not config_path.exists():
        return json.dumps({"status": "error", "error": "config.json not found"}, ensure_ascii=False)

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return json.dumps({"status": "error", "error": f"config.json parse error: {e}"}, ensure_ascii=False)

    if "source" not in config:
        return json.dumps({"status": "error", "error": "config.json missing 'source' field (tushare/okx/yfinance)"}, ensure_ascii=False)

    if config["source"] not in VALID_SOURCES:
        return json.dumps({"status": "error", "error": f"source must be one of {VALID_SOURCES}, got: {config['source']}"}, ensure_ascii=False)

    signal_path = run_path / "code" / "signal_engine.py"
    if not signal_path.exists():
        return json.dumps({"status": "error", "error": "code/signal_engine.py not found"}, ensure_ascii=False)

    agent_root = Path(__file__).resolve().parents[2]
    entry_script = agent_root / "backtest" / "runner.py"

    source = config.get("source", "?")
    emit_progress(
        "simulate",
        message=f"running backtest engine (source={source})",
    )
    runner = Runner(timeout=300)
    result = runner.execute(
        entry_script,
        run_path,
        cwd=agent_root,
        cli_args=[str(run_path)],
    )

    emit_progress("finalize", message="collecting artifacts")
    artifacts_found = {name: str(path) for name, path in result.artifacts.items()}
    return json.dumps({
        "status": "ok" if result.success else "error",
        "exit_code": result.exit_code,
        "stdout": result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout,
        "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
        "artifacts": artifacts_found,
        "run_dir": run_dir,
    }, ensure_ascii=False)


def execute_backtest(*, run_dir: str, confirmed: Any = False) -> str:
    """Gate backtest behind explicit user confirmation, then run if approved."""
    if not _is_confirmed(confirmed):
        return backtest_needs_confirmation(run_dir)
    return run_backtest(run_dir)


class BacktestTool(BaseTool):
    """Backtest execution tool (requires user confirmation)."""

    name = "backtest"
    description = (
        "Run backtest after the user confirms. First call without confirmed=true "
        "returns needs_confirmation + a config preview — show that to the user. "
        "Only re-call with confirmed=true after they explicitly approve."
    )
    parameters = {
        "type": "object",
        "properties": {
            "run_dir": {"type": "string", "description": "Path to the run directory"},
            "confirmed": {
                "type": "boolean",
                "description": (
                    "Must be true only after the user explicitly approved this "
                    "backtest. Default false — returns needs_confirmation instead "
                    "of running."
                ),
                "default": False,
            },
        },
        "required": ["run_dir"],
    }
    repeatable = True
    is_readonly = False

    def execute(self, **kwargs) -> str:
        """Execute backtest only when confirmed."""
        return execute_backtest(
            run_dir=kwargs["run_dir"],
            confirmed=kwargs.get("confirmed", False),
        )
