import dbm
import json
import os
import time

import yt_dlp


DB_PATH = "db/rss-bot"
PREFETCH_INTERVAL = int(os.getenv("PREFETCH_INTERVAL", "3600"))  # default: 1 hour


def read_entry(db, key):
    """Read a db entry, handling both old (plain string) and new (JSON) formats."""
    raw = db[key].decode("utf-8")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"status": raw}


def write_entry(db, key, data):
    """Write a JSON entry to the db."""
    if isinstance(key, bytes):
        key = key.decode("utf-8")
    db[key] = json.dumps(data)


def fetch_metadata(url):
    """Fetch video metadata using yt-dlp Python API."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": 30,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        print(f"  ⚠️  Error fetching metadata for {url}: {e}")
        return None


def is_short(metadata):
    """Detect if a video is a YouTube Short / Reel."""
    if metadata is None:
        return False

    # Check duration (Shorts can be up to 3 minutes)
    duration = metadata.get("duration") or 0
    if 0 < duration <= 60:
        return True

    # Check URL patterns
    for url_field in ("webpage_url", "original_url", "url"):
        if "/shorts/" in (metadata.get(url_field) or ""):
            return True

    # Vertical aspect ratio — reliable indicator of Shorts
    width = metadata.get("width") or 0
    height = metadata.get("height") or 0
    if width > 0 and height > 0 and height > width:
        return True

    return False


def prefetch_cycle():
    """Run one prefetch cycle — enrich new entries with yt-dlp metadata."""
    print("Starting prefetch cycle...")

    entries_to_prefetch = {}
    with dbm.open(DB_PATH, "c") as db:
        for key in db.keys():
            entry = read_entry(db, key)
            if entry.get("status") == "New" and not entry.get("prefetched", False):
                url = key.decode("utf-8") if isinstance(key, bytes) else key
                entries_to_prefetch[url] = entry

    if not entries_to_prefetch:
        print("No entries to prefetch")
        return

    print(f"Prefetching metadata for {len(entries_to_prefetch)} entries...")

    for url, entry in entries_to_prefetch.items():
        print(f"Fetching: {url}")
        metadata = fetch_metadata(url)

        if metadata:
            entry["title"] = metadata.get("title", entry.get("title", "Unknown"))
            entry["channel"] = metadata.get(
                "channel",
                metadata.get("uploader", entry.get("channel", "Unknown")),
            )
            entry["duration"] = metadata.get("duration") or 0
            entry["prefetched"] = True

            if is_short(metadata):
                entry["type"] = "short"
                entry["status"] = "Filtered"
                print(f"  ⏭️  Short/Reel detected, filtered out: {entry['title']}")
            else:
                entry["type"] = "video"
                print(
                    f"  ✅ {entry['channel']}: {entry['title']} "
                    f"({entry['duration']}s)"
                )
        else:
            # Could not fetch — mark as attempted so we don't retry every cycle
            entry["prefetched"] = True
            entry["type"] = "video"
            print("  ⚠️  Could not fetch metadata, keeping RSS data")

        with dbm.open(DB_PATH, "c") as db:
            write_entry(db, url, entry)


def main():
    print("Starting prefetch service...")
    print(f"Prefetch interval: {PREFETCH_INTERVAL}s")

    while True:
        try:
            prefetch_cycle()
        except Exception as e:
            print(f"Error in prefetch cycle: {e}")

        print(f"Sleeping for {PREFETCH_INTERVAL}s...")
        time.sleep(PREFETCH_INTERVAL)


if __name__ == "__main__":
    main()
