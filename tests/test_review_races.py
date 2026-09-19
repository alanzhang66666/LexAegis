"""Exercise the real worker boundary with deterministic thread interleavings."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx

from lexaegis import review, service, worker
from lexaegis.policy import disclosure_history, ledger_usage
from .conftest import approve, demo_task, login_as


def _issue(task):
    return {"request_hash": task["request_hash"], "idempotency_key": "concurrent-technical-issue",
            "reason": "发送前发现补充线索，需要法学复核",
            "evidence_ids": [task["fact_snapshot"][0]["id"]]}


def test_veto_while_worker_prepares_skips_network_and_survives_restart(demo_env, monkeypatch):
    _, task = demo_task(demo_env)
    task = approve(demo_env, task)
    client, store = demo_env["client"], demo_env["app"].state.store
    queued = client.post(f"/api/v1/tasks/{task['id']}/send")
    queued.raise_for_status()
    preparing, resume = Event(), Event()

    def collect(*args, **kwargs):
        preparing.set()
        assert resume.wait(10)
        return None

    class NoDispatch:
        def post(self, *args, **kwargs):
            raise AssertionError("A cancelled queued request reached the gateway")

    monkeypatch.setattr(worker.release_service, "collect_context", collect)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker.process_one, store, demo_env["root"], NoDispatch())
        try:
            assert preparing.wait(10)
            login_as(demo_env, "technical_reviewer")
            blocked = client.post(f"/api/v1/tasks/{task['id']}/review-issues", json=_issue(task))
            assert blocked.status_code == 200, blocked.text
        finally:
            resume.set()
        assert future.result(timeout=10)
    worker.recover(store)
    with store.read() as repo:
        current = repo.get(task["id"], "task")
        assert current["status"] == "review_blocked"
        assert current["approval"] is None
        assert repo.get(queued.json()["id"], "job")["status"] == "cancelled"
        assert repo.get(task["request"]["request_id"], "disclosure")["status"] == "cancelled"
        assert disclosure_history(repo.list("disclosure", task["case_id"])) == []
        assert ledger_usage(repo.list("disclosure", task["case_id"])) == (0, 0)


def test_sending_boundary_prevents_false_claim_of_blocking(demo_env):
    _, task = demo_task(demo_env)
    task = approve(demo_env, task)
    client, store = demo_env["client"], demo_env["app"].state.store
    client.post(f"/api/v1/tasks/{task['id']}/send").raise_for_status()
    sending, resume = Event(), Event()

    class TimedOutGateway:
        calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            sending.set()
            assert resume.wait(10)
            raise httpx.ReadTimeout("Simulated response loss after sending began")

    gateway = TimedOutGateway()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker.process_one, store, demo_env["root"], gateway)
        try:
            assert sending.wait(10)
            login_as(demo_env, "technical_reviewer")
            rejected = client.post(f"/api/v1/tasks/{task['id']}/review-issues", json=_issue(task))
            assert rejected.status_code == 409, rejected.text
        finally:
            resume.set()
        assert future.result(timeout=10)
    worker.recover(store)
    assert not worker.process_one(store, demo_env["root"], gateway)
    assert gateway.calls == 1
    with store.read() as repo:
        assert repo.get(task["id"], "task")["status"] == "unknown"
        assert not review.list_open_issues(repo, task["case_id"])
        assert ledger_usage(repo.list("disclosure", task["case_id"]))[0] == 1


def test_enqueue_waiting_on_review_transaction_observes_revoked_approval(demo_env):
    _, task = demo_task(demo_env)
    task = approve(demo_env, task)
    store = demo_env["app"].state.store
    attempting = Event()

    def enqueue():
        attempting.set()
        try:
            with store.transaction() as repo:
                service.reserve_send(repo, task["id"])
        except ValueError:
            return "blocked"
        return "queued"

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.transaction() as repo:
            future = pool.submit(enqueue)
            assert attempting.wait(10)
            review.submit_issue(repo, repo.get(task["id"], "task"), _issue(task),
                                {"user_id": "technical-account", "actor_role": "technical_reviewer"})
        assert future.result(timeout=10) == "blocked"
    with store.read() as repo:
        assert not repo.list("disclosure", task["case_id"])
        assert not [job for job in repo.list("job", task["case_id"]) if job["kind"] == "send"]
