from __future__ import annotations

from fip_api.benchmarking import worker as benchmark_worker
from fip_api.training_operations import worker as training_worker


def test_training_worker_once_processes_at_most_one_job(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def process(**kwargs: object) -> bool:
        calls.append(kwargs)
        return False

    monkeypatch.setattr(training_worker, "process_next_training_run", process)

    assert training_worker.main(["--once"]) == 0
    assert len(calls) == 1


def test_benchmark_worker_once_processes_at_most_one_job(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def process(**kwargs: object) -> bool:
        calls.append(kwargs)
        return False

    monkeypatch.setattr(benchmark_worker, "process_next_benchmark_run", process)

    assert benchmark_worker.main(["--once"]) == 0
    assert len(calls) == 1
