"""Tests for rock.sdk.job.observability — reporter, decorator, env config."""

from __future__ import annotations

from rock import env_vars


class TestEnvVars:
    def test_otlp_endpoint_defaults_to_none(self, monkeypatch):
        monkeypatch.delenv("ROCK_JOB_METRICS_OTLP_ENDPOINT", raising=False)
        assert env_vars.ROCK_JOB_METRICS_OTLP_ENDPOINT is None

    def test_otlp_endpoint_reads_env(self, monkeypatch):
        monkeypatch.setenv("ROCK_JOB_METRICS_OTLP_ENDPOINT", "http://otlp:4318/v1/metrics")
        assert env_vars.ROCK_JOB_METRICS_OTLP_ENDPOINT == "http://otlp:4318/v1/metrics"

    def test_high_cardinality_defaults_true(self, monkeypatch):
        monkeypatch.delenv("ROCK_JOB_METRICS_HIGH_CARDINALITY_LABELS", raising=False)
        assert env_vars.ROCK_JOB_METRICS_HIGH_CARDINALITY_LABELS is True

    def test_high_cardinality_false_when_set_false(self, monkeypatch):
        monkeypatch.setenv("ROCK_JOB_METRICS_HIGH_CARDINALITY_LABELS", "false")
        assert env_vars.ROCK_JOB_METRICS_HIGH_CARDINALITY_LABELS is False
