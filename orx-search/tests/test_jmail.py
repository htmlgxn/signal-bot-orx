from pathlib import Path

import httpx


def test_thread_page(thread_id):
    url = f"https://jmail.world/thread/{thread_id}?view=inbox"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    with httpx.Client(http2=True, headers=headers) as client:
        resp = client.get(url)
        print(f"Status: {resp.status_code}")
        print(f"Content length: {len(resp.content)}")

        with Path("thread_output.html").open("w") as f:
            f.write(resp.text)

        # Check for common email body markers
        if "from" in resp.text.lower() and "to" in resp.text.lower():
            print("Found potential email headers (From/To)!")

        # Look for the specific thread ID in the content
        if thread_id in resp.text:
            print(f"Found thread ID {thread_id} in page content!")


if __name__ == "__main__":
    # From previous test: EFTA02639428 was a match
    test_thread_page("EFTA02639428")
