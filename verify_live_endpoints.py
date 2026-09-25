"""
Live HTTP Endpoint Verification Script.
Connects to http://localhost:8080 and verifies:
1. GET  /v1/healthz
2. GET  /v1/metadata
3. POST /v1/context (push category, merchant, customer, trigger + 409 stale version check)
4. POST /v1/tick (message generation, suppression, format checks)
5. POST /v1/reply (auto-reply, hostile, intent-transition, curveball)
"""

import json
import sys
from urllib import request as urlrequest, error as urlerror

BASE_URL = "http://127.0.0.1:8080"


def make_request(method: str, path: str, body: dict = None):
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    req = urlrequest.Request(url, data=data, headers=headers, method=method)
    try:
        with urlrequest.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, e.reason
    except Exception as e:
        return 0, str(e)


def main():
    # Reset state
    make_request("POST", "/v1/teardown")
    print("=== 1. Testing GET /v1/healthz ===", flush=True)
    status, res = make_request("GET", "/v1/healthz")
    print(f"Status: {status}, Response: {res}")
    assert status == 200 and res["status"] == "ok"
    print("PASS: /v1/healthz")

    print("\n=== 2. Testing GET /v1/metadata ===")
    status, res = make_request("GET", "/v1/metadata")
    print(f"Status: {status}, Response: {res}")
    assert status == 200 and res["team_name"] == "Vera Elite"
    print("PASS: /v1/metadata")

    print("\n=== 3. Testing POST /v1/context ===")
    # Push category
    cat_payload = {
        "slug": "dentists",
        "voice": {"tone": "peer_clinical", "vocab_taboo": ["guaranteed"]},
        "offer_catalog": [{"id": "den_001", "title": "Dental Cleaning @ ₹299"}],
        "peer_stats": {"avg_rating": 4.4, "avg_ctr": 0.030},
        "digest": [{"id": "d_2026W17_jida_fluoride", "source": "JIDA Oct 2026, p.14", "title": "Fluoride trial", "trial_n": 2100}]
    }
    status, res = make_request("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 1, "payload": cat_payload
    })
    print(f"Category push v1: {status} -> {res}")
    assert status == 200 and res["accepted"] is True

    # Same version re-push -> idempotent (no-op, 200)
    status, res = make_request("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 1, "payload": cat_payload
    })
    print(f"Same version re-push: {status} -> {res}")
    assert status == 200 and res["accepted"] is True, f"Expected idempotent 200, got {status}"

    # Push v2 to advance version
    status, res = make_request("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 2, "payload": cat_payload
    })
    print(f"Category push v2: {status} -> {res}")
    assert status == 200 and res["accepted"] is True

    # Now push v1 again (lower than current v2) -> 409 stale_version
    status, res = make_request("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 1, "payload": cat_payload
    })
    print(f"Stale version push (v1 after v2): {status} -> {res}")
    assert status == 409 and res["accepted"] is False and res["reason"] == "stale_version"

    # Push merchant
    merch_payload = {
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "category_slug": "dentists",
        "identity": {"name": "Dr. Meera's Dental Clinic", "owner_first_name": "Meera", "locality": "Lajpat Nagar", "city": "Delhi"},
        "performance": {"views": 2410, "calls": 18, "ctr": 0.021},
        "offers": [{"id": "o_1", "title": "Dental Cleaning @ ₹299", "status": "active"}]
    }
    status, res = make_request("POST", "/v1/context", {
        "scope": "merchant", "context_id": "m_001_drmeera_dentist_delhi", "version": 1, "payload": merch_payload
    })
    print(f"Merchant push: {status} -> {res}")
    assert status == 200 and res["accepted"] is True

    # Push trigger
    trg_payload = {
        "id": "trg_001_research_digest_dentists",
        "scope": "merchant",
        "kind": "research_digest",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
        "suppression_key": "research:dentists:2026-W17"
    }
    status, res = make_request("POST", "/v1/context", {
        "scope": "trigger", "context_id": "trg_001_research_digest_dentists", "version": 1, "payload": trg_payload
    })
    print(f"Trigger push: {status} -> {res}")
    assert status == 200 and res["accepted"] is True

    # Re-check healthz context count
    status, res = make_request("GET", "/v1/healthz")
    print(f"Healthz updated: {res['contexts_loaded']}")
    assert res["contexts_loaded"]["category"] == 1
    assert res["contexts_loaded"]["merchant"] == 1
    assert res["contexts_loaded"]["trigger"] == 1
    print("PASS: /v1/context & /v1/healthz count update")

    print("\n=== 4. Testing POST /v1/tick ===")
    status, res = make_request("POST", "/v1/tick", {
        "now": "2026-04-26T10:35:00Z",
        "available_triggers": ["trg_001_research_digest_dentists"]
    })
    print(f"Status: {status}, Actions returned: {len(res['actions'])}")
    assert status == 200 and len(res["actions"]) == 1
    action = res["actions"][0]
    print(f"Action Body: {action['body']}")
    assert "Dr. Meera" in action["body"]
    assert "2,100" in action["body"] or "2100" in action["body"]
    assert action["cta"] in ["binary_yes_no", "open_ended"]
    print("PASS: /v1/tick")

    print("\n=== 5. Testing POST /v1/reply ===")
    # 5a. Auto-reply detection
    status, res = make_request("POST", "/v1/reply", {
        "conversation_id": "conv_live_1",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "from_role": "merchant",
        "message": "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly.",
        "turn_number": 2
    })
    print(f"Auto-reply test: action={res['action']}")
    assert status == 200 and res["action"] == "end"

    # 5b. Hostility detection
    status, res = make_request("POST", "/v1/reply", {
        "conversation_id": "conv_live_2",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "from_role": "merchant",
        "message": "Stop messaging me. This is useless spam.",
        "turn_number": 2
    })
    print(f"Hostile test: action={res['action']}")
    assert status == 200 and res["action"] == "end"

    # 5c. Intent transition
    status, res = make_request("POST", "/v1/reply", {
        "conversation_id": "conv_live_3",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "from_role": "merchant",
        "message": "Ok lets do it. Whats next?",
        "turn_number": 2
    })
    print(f"Intent transition test: action={res['action']}, body=\"{res.get('body', '')}\"")
    assert status == 200 and res["action"] == "send"
    body_l = res["body"].lower()
    actioning = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
    qualifying = ["would you", "do you", "can you tell", "what if", "how about"]
    assert any(w in body_l for w in actioning)
    assert not any(w in body_l for w in qualifying)

    # 5d. Curveball
    status, res = make_request("POST", "/v1/reply", {
        "conversation_id": "conv_live_4",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "from_role": "merchant",
        "message": "Can you also help me file my GST returns this quarter?",
        "turn_number": 2
    })
    print(f"Curveball test: action={res['action']}, body=\"{res.get('body', '')}\"")
    assert status == 200 and res["action"] == "send"
    assert "gst" in res["body"].lower() or "tax" in res["body"].lower()

    print("PASS: /v1/reply (all scenarios)")

    print("\n==============================================")
    print("ALL 5 LIVE ENDPOINTS VERIFIED SUCCESSFULLY!")
    print("==============================================")


if __name__ == "__main__":
    main()
