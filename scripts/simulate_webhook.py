"""
scripts/simulate_webhook.py – Simulate a Meetily summary.completed webhook event.
Owned by Karthik.

Usage:
    python -m scripts.simulate_webhook [meeting_id]

Sends a correctly HMAC-signed fake event to our webhook receiver so we can
test and demo without a live Meetily meeting.

Requires:
    MEETILY_WEBHOOK_SECRET in .env (same secret the receiver uses to verify)
"""
import hashlib
import hmac as hmac_mod
import json
import sys
import time
import uuid
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

import httpx


def main():
    secret = os.getenv("MEETILY_WEBHOOK_SECRET", "")
    if not secret:
        print("ERROR: MEETILY_WEBHOOK_SECRET not set in .env")
        print("  Set it to any string for local testing, e.g.:")
        print("  MEETILY_WEBHOOK_SECRET=test-secret-123")
        sys.exit(1)

    meeting_id = sys.argv[1] if len(sys.argv) > 1 else "mock-meeting-001"
    receiver_url = "http://127.0.0.1:8000/api/webhooks/meetily"

    # Build the event payload (Meetily event envelope)
    event = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "event": "summary.completed",
        "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "resource": {
            "kind": "summary",
            "id": meeting_id,
        },
        "meeting_id": meeting_id,
        "delivery_id": str(uuid.uuid4()),
    }

    body = json.dumps(event, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))

    # Compute HMAC signature
    mac = hmac_mod.new(
        secret.encode(),
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    signature = f"sha256={mac}"

    print(f"Sending simulated summary.completed event to {receiver_url}")
    print(f"  Meeting ID: {meeting_id}")
    print(f"  Event ID: {event['event_id']}")
    print(f"  Timestamp: {timestamp}")
    print(f"  Signature: {signature[:40]}...")
    print()

    try:
        resp = httpx.post(
            receiver_url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Meetily-Signature": signature,
                "X-Meetily-Timestamp": timestamp,
            },
            timeout=10.0,
        )
        print(f"Response: {resp.status_code}")
        print(f"Body: {resp.text}")

        if resp.status_code == 200:
            print("\n[OK] Webhook accepted!")
        elif resp.status_code == 401:
            print("\n[FAIL] Signature rejected -- check that MEETILY_WEBHOOK_SECRET matches")
        else:
            print(f"\n[WARN] Unexpected response code: {resp.status_code}")

    except httpx.ConnectError:
        print(f"[FAIL] Could not connect to {receiver_url}")
        print("  Make sure the Frameline backend is running on port 8000")
        sys.exit(1)


if __name__ == "__main__":
    main()
