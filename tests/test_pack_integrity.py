from lexaegis.governance import pack_content_hash, publish_pack_record, validate_formal_gate


def reviewed_pack():
    return {
        "schema_version": 2,
        "id": "pack:synthetic:1.0",
        "domain_id": "synthetic",
        "name": "纯技术测试包",
        "version": "1.0",
        "status": "reviewed",
        "review_record": "测试审核记录",
        "reviewer": "测试复核人",
        "reviewed_at": "2026-09-05T00:00:00+00:00",
        "references": ["synthetic-reference"],
        "legal_status": "reviewed",
        "dispatch_allowed": True,
        "published_scope": {"technical_test_only": True},
        "risk_weights": {
            "entity": .2, "density": .2, "context": .2,
            "combination": .2, "cross_round": .2,
        },
    }


def test_published_pack_hash_is_verifiable_and_tamper_blocks():
    published = publish_pack_record(reviewed_pack(), "named-reviewer")
    assert published["content_hash"] == pack_content_hash(published)
    attacks = [
        {"kind": kind, "outcome": "resisted"}
        for kind in ("identity", "candidate_set", "sensitive_inference", "cross_round")
    ]
    assert not validate_formal_gate(
        published,
        [{"status": "pass"}],
        attacks,
        isolation_verified=True,
    )
    published["risk_weights"]["entity"] = .9
    blockers = validate_formal_gate(
        published,
        [{"status": "pass"}],
        attacks,
        isolation_verified=True,
    )
    assert any("规则" in blocker for blocker in blockers)
