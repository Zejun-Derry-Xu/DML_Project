from scripts.report_guardrails_v4 import build


def test_missing_results_are_not_reported_as_passing(tmp_path):
    report = build(tmp_path)
    assert report.count("NOT RUN") == 10
    assert "BLOCKED" in report
    assert "own accumulated facts" in report
    assert "not Jetstream2 CPU" in report
