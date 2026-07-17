"""Tests for backtest confirmation gating."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.tools.backtest_tool import BacktestTool, execute_backtest


def _write_minimal_run(tmp_path: Path) -> Path:
    (tmp_path / "code").mkdir()
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "source": "alphavantage",
                "codes": ["AAPL.US"],
                "start_date": "2024-01-01",
                "end_date": "2024-06-30",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "code" / "signal_engine.py").write_text(
        "class SignalEngine:\n    def generate(self, data_map):\n        return {}\n",
        encoding="utf-8",
    )
    return tmp_path


def test_backtest_requires_confirmation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    run_dir = str(_write_minimal_run(tmp_path))

    with patch("src.tools.backtest_tool.safe_run_dir", return_value=tmp_path), patch(
        "src.tools.backtest_tool.run_backtest"
    ) as mock_run:
        body = json.loads(BacktestTool().execute(run_dir=run_dir))
        mock_run.assert_not_called()

    assert body["status"] == "needs_confirmation"
    assert body["preview"]["source"] == "alphavantage"
    assert body["preview"]["codes"] == ["AAPL.US"]
    assert "confirmed=true" in body["next_step"]


def test_backtest_runs_when_confirmed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    run_dir = str(_write_minimal_run(tmp_path))

    with patch(
        "src.tools.backtest_tool.run_backtest",
        return_value=json.dumps({"status": "ok", "run_dir": run_dir}),
    ) as mock_run:
        body = json.loads(
            execute_backtest(run_dir=run_dir, confirmed=True)
        )
        mock_run.assert_called_once_with(run_dir)

    assert body["status"] == "ok"
