from dotenv import load_dotenv
load_dotenv()
from backend.app import meetily_client
print("Reachable:", meetily_client.is_reachable())
meetings = meetily_client.list_meetings()
print(f"Found {len(meetings)} meetings")
for m in meetings[:5]:
    print(f"  ID: {m.get('id', '?')}  Status: {m.get('status', '?')}  Title: {m.get('title', '?')}")
    print(f"    All keys: {list(m.keys())}")
