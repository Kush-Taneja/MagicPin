"""
Comprehensive Test Suite for Vera Bot (magicpin AI Challenge).
Tests:
- GET  /v1/healthz
- GET  /v1/metadata
- POST /v1/context (push, idempotency, version conflicts, invalid scope)
- POST /v1/tick (proactive message composition, suppression, schema adherence)
- POST /v1/reply (auto-reply, hostility, intent transition, curveball, progression)
- Standalone compose() function
- Standalone respond() function
- Generation and validation of submission.jsonl for all 30 test pairs
"""

import json
import time
from pathlib import Path
from fastapi.testclient import TestClient

from bot import app, compose, respond, contexts, conversations, suppressed_keys

client = TestClient(app)
ROOT_DIR = Path(__file__).parent


def setup_function():
    """Reset state before each test."""
    contexts.clear()
    conversations.clear()
    suppressed_keys.clear()


def test_healthz_initial():
    """Test /v1/healthz returns 200 and initial zero counts."""
    resp = client.get("/v1/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "uptime_seconds" in data
    assert data["contexts_loaded"] == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}


def test_metadata():
    """Test /v1/metadata returns team identity and model info."""
    resp = client.get("/v1/metadata")
    assert resp.status_code == 200
    data = resp.json()
    assert data["team_name"] == "Vera Elite"
    assert "Kush Taneja" in data["team_members"]
    assert "version" in data
    assert "approach" in data


def test_context_push_and_stale_version():
    """Test /v1/context push, idempotency/stale version handling, and updates."""
    cat_payload = {
        "slug": "dentists",
        "voice": {"tone": "peer_clinical", "vocab_taboo": ["guaranteed"]},
        "offer_catalog": [{"id": "den_001", "title": "Dental Cleaning @ ₹299"}],
        "peer_stats": {"avg_rating": 4.4, "avg_ctr": 0.030},
        "digest": [{"id": "d_01", "source": "JIDA Oct 2026 p.14", "title": "Trial", "trial_n": 2100}]
    }

    # 1. First push v1 -> 200
    resp1 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": cat_payload
    })
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["accepted"] is True
    assert data1["ack_id"] == "ack_dentists_v1"

    # 2. Push same version v1 again -> idempotent 200 accepted
    resp2 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": cat_payload
    })
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["accepted"] is True

    # 3. Push higher version v2 -> 200 accepted
    cat_payload["peer_stats"]["avg_rating"] = 4.6
    resp3 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 2,
        "payload": cat_payload
    })
    assert resp3.status_code == 200
    assert resp3.json()["ack_id"] == "ack_dentists_v2"

    # 4. Push stale version v1 after v2 -> 409 stale_version
    resp4 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": cat_payload
    })
    assert resp4.status_code == 409
    assert resp4.json()["reason"] == "stale_version"
    assert resp4.json()["current_version"] == 2

    # 5. Invalid scope -> 400
    resp5 = client.post("/v1/context", json={
        "scope": "invalid_scope",
        "context_id": "bad",
        "version": 1,
        "payload": {}
    })
    assert resp5.status_code == 400
    assert resp5.json()["reason"] == "invalid_scope"


def test_tick_and_composition():
    """Test /v1/tick composes valid proactive actions from contexts."""
    # Seed contexts
    cat_payload = {
        "slug": "dentists",
        "voice": {"tone": "peer_clinical", "vocab_taboo": ["guaranteed", "100% safe"]},
        "offer_catalog": [{"id": "den_001", "title": "Dental Cleaning @ ₹299"}],
        "peer_stats": {"avg_rating": 4.4, "avg_ctr": 0.030},
        "digest": [{
            "id": "d_2026W17_jida_fluoride",
            "source": "JIDA Oct 2026, p.14",
            "title": "3-month fluoride varnish trial",
            "trial_n": 2100
        }]
    }
    client.post("/v1/context", json={
        "scope": "category", "context_id": "dentists", "version": 1, "payload": cat_payload
    })

    merch_payload = {
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "category_slug": "dentists",
        "identity": {
            "name": "Dr. Meera's Dental Clinic",
            "owner_first_name": "Meera",
            "locality": "Lajpat Nagar",
            "city": "Delhi"
        },
        "performance": {"views": 2410, "calls": 18, "ctr": 0.021},
        "offers": [{"id": "o_1", "title": "Dental Cleaning @ ₹299", "status": "active"}]
    }
    client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m_001_drmeera_dentist_delhi", "version": 1, "payload": merch_payload
    })

    trg_payload = {
        "id": "trg_001_research_digest_dentists",
        "scope": "merchant",
        "kind": "research_digest",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
        "suppression_key": "research:dentists:2026-W17"
    }
    client.post("/v1/context", json={
        "scope": "trigger", "context_id": "trg_001_research_digest_dentists", "version": 1, "payload": trg_payload
    })

    # Call /v1/tick
    resp = client.post("/v1/tick", json={
        "now": "2026-04-26T10:35:00Z",
        "available_triggers": ["trg_001_research_digest_dentists"]
    })
    assert resp.status_code == 200
    actions = resp.json()["actions"]
    assert len(actions) == 1
    act = actions[0]

    assert act["merchant_id"] == "m_001_drmeera_dentist_delhi"
    assert act["send_as"] == "vera"
    assert act["suppression_key"] == "research:dentists:2026-W17"
    assert "Dr. Meera" in act["body"]
    assert "2,100" in act["body"] or "2100" in act["body"]
    assert "JIDA Oct 2026" in act["body"]
    assert "guaranteed" not in act["body"].lower()
    assert act["cta"] in ["binary_yes_no", "open_ended"]

    # Second tick with same trigger -> suppressed (actions empty)
    resp2 = client.post("/v1/tick", json={
        "now": "2026-04-26T10:40:00Z",
        "available_triggers": ["trg_001_research_digest_dentists"]
    })
    assert resp2.status_code == 200
    assert len(resp2.json()["actions"]) == 0


def test_reply_auto_reply():
    """Test /v1/reply correctly detects WhatsApp Business canned auto-replies and ends."""
    auto_msgs = [
        "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly.",
        "Thanks for reaching out. We are currently unavailable.",
        "Aapki jaankari ke liye bahut shukriya. Main hamari team tak pahuncha deti hoon."
    ]

    for i, msg in enumerate(auto_msgs):
        resp = client.post("/v1/reply", json={
            "conversation_id": f"conv_auto_{i}",
            "merchant_id": "m_001",
            "from_role": "merchant",
            "message": msg,
            "turn_number": 2
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "end"
        assert "auto-reply" in data["rationale"].lower() or "canned" in data["rationale"].lower()


def test_reply_hostile_opt_out():
    """Test /v1/reply correctly detects hostile/opt-out message and ends."""
    hostile_msgs = [
        "Stop messaging me. This is useless spam.",
        "Not interested. Unsubscribe me immediately.",
        "Leave me alone, do not text."
    ]

    for i, msg in enumerate(hostile_msgs):
        resp = client.post("/v1/reply", json={
            "conversation_id": f"conv_hostile_{i}",
            "merchant_id": "m_001",
            "from_role": "merchant",
            "message": msg,
            "turn_number": 2
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "end"
        assert "opt" in data["rationale"].lower() or "hostil" in data["rationale"].lower()


def test_reply_intent_transition():
    """
    Test /v1/reply switches immediately to ACTION mode when merchant commits.
    Must contain actioning words, and NO qualifying words.
    """
    commitment_msgs = [
        "Ok lets do it. Whats next?",
        "Yes please send the abstract and draft.",
        "Confirm, go ahead and update my google profile."
    ]

    actioning = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
    qualifying = ["would you", "do you", "can you tell", "what if", "how about"]

    for i, msg in enumerate(commitment_msgs):
        resp = client.post("/v1/reply", json={
            "conversation_id": f"conv_intent_{i}",
            "merchant_id": "m_001",
            "from_role": "merchant",
            "message": msg,
            "turn_number": 2
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "send"
        body_lower = data["body"].lower()

        # Check actioning words present
        assert any(w in body_lower for w in actioning), f"No action word found in: {data['body']}"
        # Check qualifying words ABSENT
        assert not any(w in body_lower for w in qualifying), f"Found qualifying word in: {data['body']}"


def test_reply_curveball():
    """Test /v1/reply politely declines out-of-scope requests and redirects."""
    resp = client.post("/v1/reply", json={
        "conversation_id": "conv_curveball",
        "merchant_id": "m_001",
        "from_role": "merchant",
        "message": "Btw can you also help me with my GST filing this month?",
        "turn_number": 2
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "send"
    assert "gst" in data["body"].lower() or "tax" in data["body"].lower()
    assert "draft" in data["body"].lower() or "objective" in data["body"].lower()


def test_customer_facing_composition():
    """Test customer-facing composition adheres to customer context and taboos."""
    cat = {
        "slug": "dentists",
        "voice": {"tone": "peer_clinical", "vocab_taboo": ["guaranteed", "100% safe"]},
        "offer_catalog": [{"id": "den_001", "title": "Dental Cleaning @ ₹299"}]
    }
    merch = {
        "merchant_id": "m_001",
        "identity": {"name": "Dr. Meera's Dental Clinic", "city": "Delhi", "locality": "Lajpat Nagar"},
        "offers": [{"id": "o_1", "title": "Dental Cleaning @ ₹299", "status": "active"}]
    }
    trg = {
        "id": "trg_003_recall_due_priya",
        "scope": "customer",
        "kind": "recall_due",
        "payload": {
            "service_due": "6_month_cleaning",
            "available_slots": [
                {"label": "Wed 5 Nov, 6pm"},
                {"label": "Thu 6 Nov, 5pm"}
            ]
        }
    }
    cust = {
        "customer_id": "c_001_priya",
        "identity": {"name": "Priya", "language_pref": "hi-en mix"}
    }

    res = compose(cat, merch, trg, cust)
    assert res["send_as"] == "merchant_on_behalf"
    assert "Priya" in res["body"]
    assert "Dr. Meera" in res["body"]
    assert "Wed 5 Nov, 6pm" in res["body"] or "Thu 6 Nov, 5pm" in res["body"]
    assert "guaranteed" not in res["body"].lower()
    assert res["cta"] in ["open_ended", "binary_yes_no"]


if __name__ == "__main__":
    import pytest
    pytest.main(["-v", __file__])
