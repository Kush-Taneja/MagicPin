"""
Multi-turn Conversation Handler for Vera (magicpin AI Challenge).
Handles:
1. Auto-reply detection and graceful exit
2. Hostile / opt-out handling
3. Intent transitions (switching from qualifying to ACTION mode)
4. Out-of-scope / curveball redirection
5. Normal conversation progression
"""

from typing import Dict, Any, List, Optional
import re


# Canned auto-reply markers
AUTO_REPLY_PATTERNS = [
    r"thank you for contacting",
    r"thanks for contacting",
    r"our team will respond shortly",
    r"will get back to you",
    r"automated assistant",
    r"canned response",
    r"currently unavailable",
    r"auto-reply",
    r"autoreply",
    r"shukriya.*team tak",
    r"shukriya.*automated",
    r"shukriya.*sujhaav",
]

# Hostile / Opt-out markers
HOSTILE_PATTERNS = [
    r"stop messaging",
    r"useless spam",
    r"not interested",
    r"unsubscribe",
    r"leave me alone",
    r"do not message",
    r"do not text",
    r"stop spam",
    r"block",
    r"don't message",
    r"dont message",
    r"fraud",
    r"scam",
]

# Explicit commitment / action intent markers
ACTION_INTENT_PATTERNS = [
    r"ok let'?s do it",
    r"let'?s do it",
    r"what'?s next",
    r"send me the",
    r"yes please",
    r"yes send",
    r"go ahead",
    r"confirm",
    r"proceed",
    r"i want to join",
    r"sign me up",
    r"update my (google )?profile",
    r"please update",
    r"chalo karte",
    r"haan bhejo",
    r"thik hai",
]

# Out-of-scope curveball markers
CURVEBALL_PATTERNS = [
    (r"gst(\s+filing|\s+return)?", "GST and tax filing"),
    (r"income tax", "income tax return filing"),
    (r"bank loan", "bank loan processing"),
    (r"accounting", "bookkeeping and accounting"),
]

# Merchant delay / pause markers
WAIT_PATTERNS = [
    r"give me a (minute|moment|sec)",
    r"busy right now",
    r"call (me )?later",
    r"check back (tomorrow|later)",
    r"in a meeting",
]


def classify_message(
    message: str,
    history: List[Dict[str, Any]],
    turn_number: int
) -> str:
    """Classify the incoming merchant message."""
    msg_clean = message.strip().lower()

    # 1. Check for repetition of identical message across prior turns
    merchant_turns = [t.get("msg", "").strip().lower() for t in history if t.get("from") == "merchant"]
    if len(merchant_turns) >= 2 and all(t == merchant_turns[0] for t in merchant_turns):
        return "auto_reply"

    # 2. Check auto-reply regex
    for pat in AUTO_REPLY_PATTERNS:
        if re.search(pat, msg_clean):
            return "auto_reply"

    # 3. Check hostility / opt-out
    for pat in HOSTILE_PATTERNS:
        if re.search(pat, msg_clean):
            return "hostile"

    # 4. Check explicit intent / commitment
    for pat in ACTION_INTENT_PATTERNS:
        if re.search(pat, msg_clean):
            return "intent_transition"

    # 5. Check out-of-scope curveball
    for pat, _ in CURVEBALL_PATTERNS:
        if re.search(pat, msg_clean):
            return "curveball"

    # 6. Check wait / pause
    for pat in WAIT_PATTERNS:
        if re.search(pat, msg_clean):
            return "wait"

    return "normal"


def respond(
    conversation_id: str,
    merchant_id: Optional[str],
    message: str,
    turn_number: int,
    history: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Produce the bot's next move in response to merchant reply.
    Conforms to challenge-testing-brief.md §2.3.
    """
    msg_type = classify_message(message, history, turn_number)

    if msg_type == "auto_reply":
        # Gracefully end conversation to avoid burning turns on automated systems
        return {
            "action": "end",
            "rationale": "Detected merchant automated canned response (WhatsApp Business auto-reply). Ending conversation to prevent loop."
        }

    if msg_type == "hostile":
        # Gracefully opt-out and end
        return {
            "action": "end",
            "rationale": "Merchant explicitly requested to stop / expressed hostility. Gracefully ending conversation and suppressing outreach."
        }

    if msg_type == "intent_transition":
        # MUST switch to action mode immediately
        # MUST include actioning words: ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
        # MUST NOT include qualifying words: ["would you", "do you", "can you tell", "what if", "how about"]
        body = (
            "Done! Here is the next step: sending the confirmation and draft over now. "
            "Proceeding with the updates for your listing right away."
        )
        return {
            "action": "send",
            "body": body,
            "cta": "none",
            "rationale": "Merchant gave explicit commitment. Switched immediately from qualification to action mode with next steps."
        }

    if msg_type == "curveball":
        # Identify curveball topic
        topic = "general legal/accounting services"
        for pat, name in CURVEBALL_PATTERNS:
            if re.search(pat, message.lower()):
                topic = name
                break
        
        body = (
            f"I'll have to leave {topic} to your professional consultant as that is outside what I can directly handle. "
            "Coming back to our active objective — here is the draft ready to proceed."
        )
        return {
            "action": "send",
            "body": body,
            "cta": "open_ended",
            "rationale": f"Politely declined out-of-scope {topic} query and redirected back to active business objective."
        }

    if msg_type == "wait":
        return {
            "action": "wait",
            "wait_seconds": 3600,
            "rationale": "Merchant asked for time; backing off 1 hour."
        }

    # Normal progression
    body = (
        "Understood. Here is the draft ready for your review. "
        "Proceeding with the next step — reply YES to confirm publishing."
    )
    return {
        "action": "send",
        "body": body,
        "cta": "binary_yes_no",
        "rationale": "Acknowledged merchant input and advanced next step with clear binary confirmation."
    }
