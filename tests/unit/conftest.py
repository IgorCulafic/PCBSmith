"""Keep frozen board-job contract suites on their historical policy.

New default-policy coverage lives in test_routing_policy.py. This changes only
synthetic fixture construction; no retained project ledger is rewritten.
"""

import pytest


@pytest.fixture(autouse=True)
def historical_board_job_policy(request, monkeypatch):
    if request.node.path.name in {
        "test_board_job.py",
        "test_board_job_asset_identity.py",
        "test_board_job_backend_transition.py",
        "test_board_job_continuation.py",
        "test_board_job_diagnostic.py",
        "test_board_job_edit_retry.py",
        "test_board_job_pre_native_recovery.py",
        "test_board_job_review_collision.py",
        "test_board_job_timing.py",
    }:
        monkeypatch.setattr("pcbsmith.board_job.NEW_JOB_ROUTING_POLICY", None)
