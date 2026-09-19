import copy
import json
import pytest
from .conftest import demo_task
from lexaegis.synthetic_scope import validate_synthetic_request
from lexaegis.worker import process_one


def test_gateway_reconstructs_allowed_synthetic_body(demo_env):
    case, task = demo_task(demo_env, "human_veto")
    client = demo_env["client"]
    result = client.post(f"/api/v1/tasks/{task['id']}/evaluate").json()
    request = result["request"]
    validate_synthetic_request(request)
    forged = copy.deepcopy(request)
    forged["body"]["messages"][1]["content"] = json.dumps({"facts": [{"text": "任意客户真实材料"}]})
    with pytest.raises(ValueError, match="快照"):
        validate_synthetic_request(forged)
    forged["wire_payload"]["facts"][0]["text"] = "任意客户真实材料"
    forged["body"]["messages"][1]["content"] = json.dumps(forged["wire_payload"])
    with pytest.raises(ValueError, match="登记材料"):
        validate_synthetic_request(forged)


@pytest.mark.parametrize("field", ["extra", "task", "id"])
def test_synthetic_body_cannot_hide_customer_text_in_metadata(demo_env, field):
    _, task = demo_task(demo_env)
    request = demo_env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate").json()["request"]
    wire = request["wire_payload"]
    if field == "extra":
        wire["customer_note"] = "客户真实材料"
    elif field == "task":
        wire["task"]["instructions"] = "客户真实材料"
    else:
        wire["facts"][0]["id"] = "客户真实材料"
    request["body"]["messages"][1]["content"] = json.dumps(wire)
    with pytest.raises(ValueError):
        validate_synthetic_request(request)


@pytest.mark.parametrize("nested", [False, True])
def test_duplicate_json_keys_cannot_hide_customer_text(demo_env, nested):
    _, task = demo_task(demo_env)
    request = demo_env["client"].post(f"/api/v1/tasks/{task['id']}/evaluate").json()["request"]
    content = request["body"]["messages"][1]["content"]
    if nested:
        content = content.replace('"text":', '"text":"REAL CUSTOMER SECRET", "text":', 1)
    else:
        content = '{"facts":"REAL CUSTOMER SECRET",' + content[1:]
    # Ordinary JSON decoding loses the hidden text and appears identical.
    assert json.loads(content) == request["wire_payload"]
    request["body"]["messages"][1]["content"] = content
    with pytest.raises(ValueError, match="快照"):
        validate_synthetic_request(request)


def test_offline_attack_execution_uses_no_external_client(demo_env):
    case, task = demo_task(demo_env)
    client = demo_env["client"]
    client.post(f"/api/v1/tasks/{task['id']}/evaluate").raise_for_status()
    queued = client.post(f"/api/v1/tasks/{task['id']}/attacks/run", json={"auxiliary": {}})
    assert queued.status_code == 200, queued.text

    class NoNetwork:
        def post(self, *args, **kwargs):
            raise AssertionError("offline demo must not call an external service")

    assert process_one(demo_env["app"].state.store, demo_env["root"], redteam_client=NoNetwork())
    rows = client.get(f"/api/v1/tasks/{task['id']}/attacks").json()
    assert len(rows) == 4
    assert all(row["provenance"] == "simulation" for row in rows)
    assert all(row["outcome"] in {"uncertain", "succeeded", "resisted"} for row in rows)
    assert all(row["evidence"] and row["input_hash"] and row["protocol_version"] for row in rows)
    assert client.post(f"/api/v1/tasks/{task['id']}/attacks/run", json={"auxiliary": {"identity": [{"text": "未登记正文"}]}}).status_code == 409
