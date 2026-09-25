"""
magicpin AI Challenge — Vera Bot
================================
HTTP Server & Autonomous Engagement Engine.

Endpoints live:
- GET  /v1/healthz
- GET  /v1/metadata
- POST /v1/context
- POST /v1/tick
- POST /v1/reply
- POST /v1/teardown (optional cleanup)

Standalone interface:
- compose(category, merchant, trigger, customer=None) -> dict
- respond(state, merchant_message) -> dict
"""

import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

from composer import compose as compose_message
from conversation import respond as handle_reply

app = FastAPI(title="Vera Bot - magicpin AI Challenge", version="1.0.0")
START_TIME = time.time()

# In-memory context and state stores
# Key: (scope, context_id) -> {"version": int, "payload": dict}
contexts: Dict[tuple, Dict[str, Any]] = {}
# Key: conversation_id -> list of {"from": str, "msg": str}
conversations: Dict[str, List[Dict[str, Any]]] = {}
# Suppression tracker: set of suppression_keys
suppressed_keys: set = set()


# =============================================================================
# STANDALONE INTERFACES (as defined in challenge-brief.md §7.1 & §7.4)
# =============================================================================

def compose(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None
) -> dict:
    """
    Deterministic message composition.
    Inputs are dicts loaded from context or JSON.
    Returns: {body, cta, send_as, suppression_key, rationale}
    """
    return compose_message(category, merchant, trigger, customer)


def respond(state: Any, merchant_message: str) -> dict:
    """
    Produce bot reply given conversation state and merchant message.
    """
    history = []
    turn_number = 2
    conv_id = "default"
    merchant_id = None

    if isinstance(state, dict):
        history = state.get("history", [])
        turn_number = state.get("turn_number", 2)
        conv_id = state.get("conversation_id", "default")
        merchant_id = state.get("merchant_id")
    elif isinstance(state, list):
        history = state
        turn_number = len(history) + 1

    return handle_reply(conv_id, merchant_id, merchant_message, turn_number, history)


# =============================================================================
# HELPER LOOKUP UTILITIES
# =============================================================================

def _find_context(scope: str, context_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Lookup context by exact key, or prefix/attribute match."""
    if not context_id:
        return None

    # 1. Exact match
    key = (scope, context_id)
    if key in contexts:
        return contexts[key].get("payload")

    # 2. Check by payload internal ID / slug
    id_field = "merchant_id" if scope == "merchant" else "customer_id" if scope == "customer" else "slug" if scope == "category" else "id"
    for (s, cid), data in contexts.items():
        if s == scope:
            payload = data.get("payload", {})
            if payload.get(id_field) == context_id or cid == context_id:
                return payload
            # Partial match (e.g. m_001 in m_001_drmeera_dentist_delhi)
            if context_id in cid or cid in context_id:
                return payload

    return None


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/v1/healthz")
async def healthz():
    """Liveness probe reporting uptime and context counts."""
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _), _ in contexts.items():
        if scope in counts:
            counts[scope] += 1
        else:
            counts[scope] = 1

    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": counts
    }


@app.get("/v1/metadata")
async def metadata():
    """Bot identity and model metadata."""
    return {
        "team_name": "Vera Elite",
        "team_members": ["Kush Taneja"],
        "model": "deterministic-context-composer-v1",
        "approach": "deterministic 4-context composition engine with domain voice adaptation and conversational state machine",
        "contact_email": "kushtaneja@magicpin.com",
        "version": "1.0.0",
        "submitted_at": "2026-04-26T08:00:00Z"
    }


class CtxBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: Optional[str] = None


@app.post("/v1/context")
async def push_context(body: CtxBody):
    """
    Ingest or update context across category, merchant, customer, or trigger scopes.
    Idempotent on (scope, context_id, version).
    Replaces atomically if higher version; returns 409 if stale version.
    """
    valid_scopes = {"category", "merchant", "customer", "trigger"}
    if body.scope not in valid_scopes:
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "invalid_scope", "details": f"Unknown scope: {body.scope}"}
        )

    key = (body.scope, body.context_id)
    cur = contexts.get(key)

    if cur and cur.get("version", 0) > body.version:
        return JSONResponse(
            status_code=409,
            content={
                "accepted": False,
                "reason": "stale_version",
                "current_version": cur.get("version", 0)
            }
        )

    # Store context payload atomically
    contexts[key] = {
        "version": body.version,
        "payload": body.payload
    }

    if body.scope == "trigger":
        supp_key = body.payload.get("suppression_key")
        if supp_key and supp_key in suppressed_keys:
            suppressed_keys.discard(supp_key)

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": now_iso
    }


class TickBody(BaseModel):
    now: Optional[str] = None
    available_triggers: List[str] = []


@app.post("/v1/tick")
async def tick(body: TickBody):
    """
    Periodic wake-up for proactive engagement.
    Inspects available triggers, composes messages, and returns zero or more actions.
    """
    actions = []

    for trg_id in body.available_triggers:
        # Retrieve trigger context
        trg_ctx = _find_context("trigger", trg_id)
        if not trg_ctx:
            continue

        # Extract trigger attributes
        trg_payload = trg_ctx.get("payload", {}) if isinstance(trg_ctx.get("payload"), dict) else {}
        merchant_id = trg_ctx.get("merchant_id") or trg_payload.get("merchant_id")
        customer_id = trg_ctx.get("customer_id") or trg_payload.get("customer_id")
        suppression_key = trg_ctx.get("suppression_key") or f"trg:{trg_id}"

        # Check suppression
        if suppression_key in suppressed_keys:
            continue

        # Lookup merchant
        merchant = _find_context("merchant", merchant_id)
        if not merchant:
            continue

        # Lookup category
        category_slug = merchant.get("category_slug") or trg_payload.get("category")
        category = _find_context("category", category_slug)
        if not category:
            # Fallback search any category
            for (s, _), data in contexts.items():
                if s == "category":
                    category = data.get("payload")
                    break

        if not category:
            continue

        # Lookup customer if customer-scoped
        customer = _find_context("customer", customer_id) if customer_id else None

        # Compose message
        composed = compose_message(category, merchant, trg_ctx, customer)

        # Mark suppression key
        suppressed_keys.add(suppression_key)

        # Register conversation
        conv_id = f"conv_{merchant_id}_{trg_id}"
        conversations.setdefault(conv_id, []).append({"from": "vera", "msg": composed["body"]})

        actions.append({
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": composed.get("send_as", "vera"),
            "trigger_id": trg_id,
            "template_name": composed.get("template_name", f"vera_{trg_ctx.get('kind', 'generic')}_v1"),
            "template_params": composed.get("template_params", []),
            "body": composed["body"],
            "cta": composed.get("cta", "binary_yes_no"),
            "suppression_key": suppression_key,
            "rationale": composed.get("rationale", "Composed from category + merchant + trigger context")
        })

    return {"actions": actions}


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: Optional[str] = None
    turn_number: int = 1


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    """
    Handle inbound reply from simulated merchant or customer.
    Detects auto-reply, hostility, commitment/intent, curveball, or normal progression.
    """
    # Track conversation turn
    history = conversations.setdefault(body.conversation_id, [])
    history.append({"from": body.from_role, "msg": body.message})

    # Generate response
    resp = handle_reply(
        body.conversation_id,
        body.merchant_id,
        body.message,
        body.turn_number,
        history
    )

    if resp.get("action") == "send" and "body" in resp:
        history.append({"from": "vera", "msg": resp["body"]})

    return resp


@app.post("/v1/teardown")
async def teardown():
    """Wipe session state at end of test as permitted in challenge-testing-brief.md §11."""
    contexts.clear()
    conversations.clear()
    suppressed_keys.clear()
    return {"status": "ok", "message": "All session context and conversation state wiped"}


if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=8080, reload=False)
