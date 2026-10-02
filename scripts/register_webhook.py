"""
scripts/register_webhook.py – Register the Frameline webhook with Meetily.
Owned by Karthik.

Usage:
    python -m scripts.register_webhook

Registers http://127.0.0.1:8000/api/webhooks/meetily for the summary.completed event.
Prints the hmac_secret (shown only once by Meetily – save it immediately to .env).

Requires:
    MEETILY_BASE_URL and MEETILY_API_KEY in .env

After registration, you MUST approve the destination in Meetily:
    Settings > Integrations > Advanced > Destinations > Allow
"""
import json
import sys
import os

# Add repo root to path so we can import backend modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

import httpx


def main():
    base_url = os.getenv("MEETILY_BASE_URL", "http://127.0.0.1:8420")
    api_key = os.getenv("MEETILY_API_KEY", "")
    external_url = os.getenv("FRAMELINE_EXTERNAL_URL", "http://127.0.0.1:8000")

    if not api_key:
        print("ERROR: MEETILY_API_KEY not set in .env")
        sys.exit(1)

    webhook_url = f"{external_url.rstrip('/')}/api/webhooks/meetily"

    print(f"Registering webhook with Meetily at {base_url}")
    print(f"  Receiver URL: {webhook_url}")
    print(f"  Events: summary.completed")
    print()

    try:
        with httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15.0,
        ) as client:
            # First, check if we can reach Meetily
            health = client.get("/health")
            print(f"  Meetily health: {health.status_code}")

            # Register the webhook
            resp = client.post("/v1/webhooks", json={
                "url": webhook_url,
                "events": ["summary.completed"],
                "delivery_mode": "at-least-once",
            })

            if resp.status_code == 201:
                data = resp.json()
                print()
                print("[OK] Webhook registered successfully!")
                print(f"  Webhook ID: {data.get('id')}")
                print(f"  URL: {data.get('url')}")
                print(f"  Events: {data.get('events')}")
                print()
                hmac_secret = data.get("hmac_secret")
                if hmac_secret:
                    print("=" * 60)
                    print("[!] SAVE THIS SECRET -- it is shown only once!")
                    print(f"  MEETILY_WEBHOOK_SECRET={hmac_secret}")
                    print("=" * 60)
                    print()
                    # Auto-update .env file
                    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
                    if os.path.exists(env_path):
                        with open(env_path, "r", encoding="utf-8") as f:
                            lines = f.readlines()
                        new_lines = []
                        updated = False
                        for line in lines:
                            if line.startswith("MEETILY_WEBHOOK_SECRET="):
                                new_lines.append(f"MEETILY_WEBHOOK_SECRET={hmac_secret}\n")
                                updated = True
                            else:
                                new_lines.append(line)
                        if not updated:
                            new_lines.append(f"MEETILY_WEBHOOK_SECRET={hmac_secret}\n")
                        with open(env_path, "w", encoding="utf-8") as f:
                            f.writelines(new_lines)
                        print("[OK] Automatically updated MEETILY_WEBHOOK_SECRET in .env!")
                print()
                print("NEXT STEP: Approve the destination in Meetily:")
                print("  Settings > Integrations > Advanced > Destinations > Allow")
                print("  (or look for the 'Waiting for you' banner in Integrations)")
            else:
                print(f"[FAIL] Registration failed: {resp.status_code}")
                print(f"  Response: {resp.text}")
                sys.exit(1)

    except httpx.ConnectError:
        print(f"[FAIL] Could not connect to Meetily at {base_url}")
        print("  Make sure Meetily Pro is running and the Automation API is enabled.")
        print("  Settings > PRO > Integrations > Turn on")
        sys.exit(1)


if __name__ == "__main__":
    main()
