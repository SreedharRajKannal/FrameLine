"""
scripts/register_webhook.py – Register the Frameline webhook with Meetily.
Owned by Karthik.

Usage:
    python -m scripts.register_webhook
    python -m scripts.register_webhook --url https://abc123.loca.lt

Registers the receiver URL for the summary.completed event.
By default uses http://127.0.0.1:8000/api/webhooks/meetily, but Meetily
blocks loopback/private IPs so you must pass a public tunnel URL:

    1. Run in a separate terminal:
       npx localtunnel --port 8000
       (or: ngrok http 8000)
    2. Copy the public URL printed, then run:
       python -m scripts.register_webhook --url https://<tunnel-id>.loca.lt

Requires:
    MEETILY_BASE_URL and MEETILY_API_KEY in .env

After registration, you MUST approve the destination in Meetily:
    Settings > Integrations > Advanced > Destinations > Allow
"""
import argparse
import json
import sys
import os

# Add repo root to path so we can import backend modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

import httpx


def main():
    parser = argparse.ArgumentParser(description="Register Frameline webhook with Meetily")
    parser.add_argument(
        "--url",
        help="Public receiver URL (e.g. https://abc123.loca.lt). "
             "Meetily blocks 127.0.0.1/localhost so a tunnel is required.",
    )
    args = parser.parse_args()

    base_url = os.getenv("MEETILY_BASE_URL", "http://127.0.0.1:8420")
    api_key = os.getenv("MEETILY_API_KEY", "")

    if not api_key:
        print("ERROR: MEETILY_API_KEY not set in .env")
        sys.exit(1)

    if args.url:
        webhook_url = args.url.rstrip("/") + "/api/webhooks/meetily"
    else:
        webhook_url = "http://127.0.0.1:8000/api/webhooks/meetily"
        print("[!] WARNING: No --url passed. Meetily will likely reject 127.0.0.1.")
        print("    Run: npx localtunnel --port 8000")
        print("    Then retry: python -m scripts.register_webhook --url https://<id>.loca.lt")
        print()

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
                    print("Add it to your .env file now.")
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
