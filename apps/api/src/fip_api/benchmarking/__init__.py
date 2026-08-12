"""Deterministic synthetic system-benchmark orchestration."""

from fip_api.benchmarking.generator import GENERATOR_VERSION, generate_synthetic_benchmark
from fip_api.benchmarking.service import (
    BENCHMARK_REPORT_SCHEMA_VERSION,
    BENCHMARK_VOLUME_TARGET,
    SCORING_LATENCY_TARGET_MILLISECONDS,
    BenchmarkRunConflict,
    BenchmarkRunNotFound,
    BenchmarkRunStateError,
    benchmark_report_facts,
    build_benchmark_result,
    build_benchmark_run_response,
    claim_next_benchmark_run,
    complete_benchmark_run,
    fail_benchmark_run,
    get_benchmark_run,
    list_benchmark_runs,
    request_benchmark_run,
    retry_benchmark_run,
    verify_benchmark_run_integrity,
)

__all__ = [
    "BENCHMARK_REPORT_SCHEMA_VERSION",
    "BENCHMARK_VOLUME_TARGET",
    "GENERATOR_VERSION",
    "SCORING_LATENCY_TARGET_MILLISECONDS",
    "BenchmarkRunConflict",
    "BenchmarkRunNotFound",
    "BenchmarkRunStateError",
    "benchmark_report_facts",
    "build_benchmark_result",
    "build_benchmark_run_response",
    "claim_next_benchmark_run",
    "complete_benchmark_run",
    "fail_benchmark_run",
    "generate_synthetic_benchmark",
    "get_benchmark_run",
    "list_benchmark_runs",
    "request_benchmark_run",
    "retry_benchmark_run",
    "verify_benchmark_run_integrity",
]
