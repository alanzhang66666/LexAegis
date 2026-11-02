"""Synthetic gateway failures and reconciliation; no external provider calls."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from lexaegis import return_pipeline, service
from lexaegis.worker import process_one, recover
from tests.conftest import approve, demo_task
from tests.test_v3_grant_snapshot_binding import approved  # pytest fixture
from tests.test_workflow import task_state


class FailedGateway:
    def __init__(self, error): self.error, self.posts, self.gets = error, 0, 0
    def post(self, *args, **kwargs):
        self.posts += 1
        raise self.error
    def get(self, *args, **kwargs):
        self.gets += 1
        return httpx.Response(404, request=httpx.Request("GET", "http://testserver/status"))


@pytest.mark.parametrize("error", [httpx.ConnectError("connect"), httpx.ReadTimeout("read"),
                                   OSError("ambiguous I/O"), ConnectionError("ambiguous connection")])
def test_formal_after_claim_never_retries_even_on_connect_error(approved, error):
    f = approved
    with f["store"].transaction() as repo:
        service.reserve_send(repo, f["task"]["id"], release_context=f["context"])
        queued = repo.get(f["task"]["id"], "task")
        grant_id = queued["formal_release"]["grant"]["id"]
    gateway = FailedGateway(error)
    assert process_one(f["store"], f["root"], gateway_client=gateway)
    with f["store"].read() as repo:
        task = repo.get(queued["id"], "task")
        assert task["status"] == "unknown"
        assert repo.get(grant_id, "one_time_dispatch_grant")["state"] == "consumed"
        assert repo.get("v3-policy", "formal_release_policy")["status"] == "consumed"
        assert not [j for j in repo.list("job") if j["kind"] == "send" and j["status"] == "pending"]
    assert not process_one(f["store"], f["root"], gateway_client=gateway)
    assert gateway.posts == 1


@pytest.mark.parametrize("status", [400, 403, 409, 422, 500])
def test_formal_gateway_error_after_claim_does_not_claim_no_disclosure(approved, status):
    f = approved
    with f["store"].transaction() as repo:
        service.reserve_send(repo, f["task"]["id"], release_context=f["context"])
        task = repo.get(f["task"]["id"], "task")
        grant_id = task["formal_release"]["grant"]["id"]
    class ErrorGateway:
        calls = 0
        def post(self, *args, **kwargs):
            self.calls += 1
            return httpx.Response(status, request=httpx.Request("POST", "http://testserver/dispatch"))
    gateway = ErrorGateway()
    assert process_one(f["store"], f["root"], gateway)
    with f["store"].read() as repo:
        current = repo.get(task["id"], "task")
        assert current["status"] == "unknown" and current["failure_code"] == "unknown"
        assert repo.get(grant_id, "one_time_dispatch_grant")["state"] == "consumed"
        assert repo.get("v3-policy", "formal_release_policy")["status"] == "consumed"
    assert not process_one(f["store"], f["root"], gateway)
    assert gateway.calls == 1


def test_unclaimed_connect_error_waits_queued_then_retries_once(demo_env):
    case, task = demo_task(demo_env)
    approve(demo_env, task)
    demo_env["client"].post(f"/api/v1/tasks/{task['id']}/send").raise_for_status()
    failed = FailedGateway(httpx.ConnectError("connect"))
    assert process_one(demo_env["app"].state.store, demo_env["root"], failed)
    assert task_state(demo_env, case["id"], task["id"])["status"] == "queued"
    with demo_env["app"].state.store.transaction() as repo:
        job = next(j for j in repo.list("job") if j["kind"] == "send")
        assert job["status"] == "pending" and job["not_before"]
        job["not_before"] = 1
        repo.put("job", job, job["case_id"])
    assert process_one(demo_env["app"].state.store, demo_env["root"], demo_env["gate"])
    assert task_state(demo_env, case["id"], task["id"])["status"] == "complete"
    assert not process_one(demo_env["app"].state.store, demo_env["root"], demo_env["gate"])
    assert failed.posts == 1


def test_generic_oserror_is_not_proof_of_connect_failure():
    assert return_pipeline.is_connect_error(httpx.ConnectError("refused"))
    assert not return_pipeline.is_connect_error(OSError("possibly after transmission"))
    assert not return_pipeline.is_connect_error(ConnectionError("unknown stage"))
    assert not return_pipeline.is_connect_error(httpx.ReadTimeout("timeout"))


def test_recover_does_not_requeue_queued_task_with_durable_claim(approved):
    from lexaegis import release_service
    f = approved
    with f["store"].transaction() as repo:
        job = service.reserve_send(repo, f["task"]["id"], release_context=f["context"])
        task = repo.get(f["task"]["id"], "task")
        # Fault injection: persist claim but leave the task's status queued.
        release_service.mark_sending(repo, task)
        job["status"] = "running"
        repo.put("job", job, job["case_id"])
    recover(f["store"])
    with f["store"].read() as repo:
        assert repo.get(task["id"], "task")["status"] == "unknown"
        assert repo.get(job["id"], "job")["status"] == "failed"
        assert repo.get(task["formal_release"]["grant"]["id"], "one_time_dispatch_grant")["state"] == "consumed"


def test_recover_requeues_only_a_still_reserved_formal_send(approved):
    f = approved
    with f["store"].transaction() as repo:
        job = service.reserve_send(repo, f["task"]["id"], release_context=f["context"])
        job["status"] = "running"
        repo.put("job", job, job["case_id"])
    recover(f["store"])
    with f["store"].read() as repo:
        assert repo.get(job["id"], "job")["status"] == "pending"
        assert repo.get(f["task"]["id"], "task")["status"] == "queued"
    from fastapi.testclient import TestClient
    with TestClient(f["gateway"]) as client:
        assert process_one(f["store"], f["root"], client)
    assert f["provider"].calls == 1


def _unknown_demo(env):
    case, task = demo_task(env)
    task = approve(env, task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/send").raise_for_status()
    assert process_one(env["app"].state.store, env["root"], FailedGateway(httpx.ReadTimeout("timeout")))
    assert task_state(env, case["id"], task["id"])["status"] == "unknown"
    return case, task


@pytest.mark.parametrize("status", [400, 403, 409, 422, 500])
def test_reconcile_http_errors_never_fabricate_before_send_rejection(demo_env, status):
    case, task = _unknown_demo(demo_env)
    demo_env["client"].post(f"/api/v1/tasks/{task['id']}/reconcile").raise_for_status()
    class Query:
        def get(self, *args, **kwargs):
            return httpx.Response(status, request=httpx.Request("GET", "http://testserver/status"))
    assert process_one(demo_env["app"].state.store, demo_env["root"], Query())
    current = task_state(demo_env, case["id"], task["id"])
    assert current["status"] == "unknown" and current["failure_code"] == "unknown"


def test_reconcile_requests_deduplicate_pending_jobs(demo_env):
    case, task = _unknown_demo(demo_env)
    one = demo_env["client"].post(f"/api/v1/tasks/{task['id']}/reconcile")
    two = demo_env["client"].post(f"/api/v1/tasks/{task['id']}/reconcile")
    assert one.status_code == two.status_code == 200
    assert one.json()["id"] == two.json()["id"]
    with demo_env["app"].state.store.read() as repo:
        assert len([j for j in repo.list("job", case["id"]) if j["kind"] == "reconcile" and j["status"] == "pending"]) == 1


def test_late_reconcile_cannot_overwrite_terminal_outcome(demo_env):
    env = demo_env
    case, task = demo_task(env)
    approve(env, task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/send").raise_for_status()
    class Gateway:
        posts = 0
        gets = 0
        def post(self, *args, **kwargs):
            self.posts += 1
            env["gate"].post(*args, **kwargs).raise_for_status()
            raise httpx.ReadTimeout("reply lost after gateway accepted")
        def get(self, *args, **kwargs):
            self.gets += 1
            if self.gets > 1: raise httpx.ReadTimeout("late query")
            return env["gate"].get(*args, **kwargs)
    gateway = Gateway()
    assert process_one(env["app"].state.store, env["root"], gateway)
    with env["app"].state.store.transaction() as repo:
        service.queue_job(repo, case["id"], "reconcile", {"task_id":task["id"]})
        service.queue_job(repo, case["id"], "reconcile", {"task_id":task["id"]})
    assert process_one(env["app"].state.store, env["root"], gateway)
    assert task_state(env, case["id"], task["id"])["status"] == "complete"
    assert process_one(env["app"].state.store, env["root"], gateway)
    assert task_state(env, case["id"], task["id"])["status"] == "complete"
    assert gateway.posts == 1 and gateway.gets == 1


def test_recovery_of_stale_reconcile_preserves_completed_task(demo_env):
    env = demo_env
    case, task = demo_task(env)
    approve(env, task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/send").raise_for_status()
    assert process_one(env["app"].state.store, env["root"], env["gate"])
    with env["app"].state.store.transaction() as repo:
        job = service.queue_job(repo, case["id"], "reconcile", {"task_id":task["id"]})
        job["status"] = "running"
        repo.put("job", job, case["id"])
    recover(env["app"].state.store)
    with env["app"].state.store.read() as repo:
        assert repo.get(task["id"], "task")["status"] == "complete"
        assert repo.get(job["id"], "job")["status"] == "cancelled"


def test_reconcile_result_arriving_after_terminal_transition_is_discarded(demo_env):
    from lexaegis import orchestrator
    env = demo_env
    case, task = _unknown_demo(env)
    env["client"].post(f"/api/v1/tasks/{task['id']}/reconcile").raise_for_status()
    entered, resume = Event(), Event()
    class SlowQuery:
        def get(self, *args, **kwargs):
            entered.set()
            assert resume.wait(10)
            return httpx.Response(404, request=httpx.Request("GET", "http://testserver/status"))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(process_one, env["app"].state.store, env["root"], SlowQuery())
        try:
            assert entered.wait(10)
            with env["app"].state.store.transaction() as repo:
                current = repo.get(task["id"], "task")
                orchestrator.transition_task(repo, current, "complete", "STATE_TRANSITION")
                repo.put("task", current, case["id"])
        finally:
            resume.set()
        assert future.result(timeout=10)
    with env["app"].state.store.read() as repo:
        assert repo.get(task["id"], "task")["status"] == "complete"
        job = next(j for j in repo.list("job", case["id"]) if j["kind"] == "reconcile")
        assert job["status"] == "cancelled"


@pytest.mark.parametrize("bad_field", ["id", "request_hash", "status"])
def test_reconcile_rejects_unbound_or_invalid_gateway_record(demo_env, bad_field):
    case, task = _unknown_demo(demo_env)
    demo_env["client"].post(f"/api/v1/tasks/{task['id']}/reconcile").raise_for_status()
    record = {"id":task["request"]["request_id"], "request_hash":task["request_hash"],
              "status":"complete", "result":{"claims":[], "unused_fact_ids":[], "gaps":[]}}
    record[bad_field] = {"id":"other-request", "request_hash":"wrong", "status":"rejected"}[bad_field]
    class Query:
        def get(self, *args, **kwargs):
            return httpx.Response(200, json=record, request=httpx.Request("GET", "http://testserver/status"))
    assert process_one(demo_env["app"].state.store, demo_env["root"], Query())
    current = task_state(demo_env, case["id"], task["id"])
    assert current["status"] == "unknown" and current["failure_code"] == "unknown"


@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ReadTimeout("late")])
def test_late_send_error_does_not_overwrite_terminal_task_or_requeue(demo_env, error):
    from lexaegis import orchestrator
    env = demo_env
    case, task = demo_task(env)
    task = approve(env, task)
    env["client"].post(f"/api/v1/tasks/{task['id']}/send").raise_for_status()
    entered, resume = Event(), Event()
    class SlowSend:
        def post(self, *args, **kwargs):
            entered.set()
            assert resume.wait(10)
            raise error
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(process_one, env["app"].state.store, env["root"], SlowSend())
        try:
            assert entered.wait(10)
            with env["app"].state.store.transaction() as repo:
                current = repo.get(task["id"], "task")
                orchestrator.transition_task(repo, current, "complete", "STATE_TRANSITION")
                repo.put("task", current, case["id"])
        finally:
            resume.set()
        assert future.result(timeout=10)
    with env["app"].state.store.read() as repo:
        assert repo.get(task["id"], "task")["status"] == "complete"
        job = next(j for j in repo.list("job", case["id"]) if j["kind"] == "send")
        assert job["status"] == "cancelled" and not job.get("not_before")


def test_formal_lost_response_reconciles_real_local_gateway_without_resend(approved):
    from fastapi.testclient import TestClient
    f = approved
    with f["store"].transaction() as repo:
        service.reserve_send(repo, f["task"]["id"], release_context=f["context"])
        task = repo.get(f["task"]["id"], "task")
        grant_id = task["formal_release"]["grant"]["id"]
    with TestClient(f["gateway"]) as client:
        class LostReply:
            posts = 0
            gets = 0
            def post(self, *args, **kwargs):
                self.posts += 1
                response = client.post(*args, **kwargs)
                response.raise_for_status()
                raise httpx.ReadTimeout("synthetic lost response after gateway accepted")
            def get(self, *args, **kwargs):
                self.gets += 1
                return client.get(*args, **kwargs)
        gateway = LostReply()
        assert process_one(f["store"], f["root"], gateway)
        with f["store"].transaction() as repo:
            assert repo.get(task["id"], "task")["status"] == "unknown"
            job = service.queue_reconciliation(repo, task["id"])
            assert job["kind"] == "reconcile"
        assert process_one(f["store"], f["root"], gateway)
        assert not process_one(f["store"], f["root"], gateway)
        with f["store"].read() as repo:
            assert repo.get(task["id"], "task")["status"] == "complete"
            assert repo.get(grant_id, "one_time_dispatch_grant")["state"] == "consumed"
            assert repo.get("v3-policy", "formal_release_policy")["status"] == "consumed"
        assert gateway.posts == 1 and gateway.gets == 1
        assert f["provider"].calls == 1
