import json

from scripts import report_optimization


def test_missing_runs_remain_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(report_optimization, "RESULTS", tmp_path)
    text = report_optimization.build()
    assert "**BLOCKED**" in text
    assert text.count("NOT RUN") == 20
    assert "human-audited" in text


def test_partial_results_are_not_completion_or_release(monkeypatch, tmp_path):
    monkeypatch.setattr(report_optimization, "RESULTS", tmp_path)
    (tmp_path / "optimization-validation31-frozen-v3-hybrid.json").write_text(
        json.dumps(
            {
                "selected": 180,
                "complete": False,
                "results": {
                    "examples": 1,
                    "per_field": {},
                    "critical_known_macro": 1.0,
                    "audited_absence_checks": 0,
                    "model_calls": 1,
                    "errors": 0,
                    "provider_fallbacks": 0,
                    "tokens": {"prompt_eval_count": 20, "eval_count": 10},
                },
            }
        )
    )
    text = report_optimization.build()
    assert "1/180 PARTIAL" in text
    assert "100.0%" in text
    assert "unreviewed" in text
    assert "**BLOCKED**" in text
