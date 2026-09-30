"""Command-line runner.

  python cli.py "Why ISRO missions cost so little" --community SpaceNerds --language hinglish
  python cli.py --batch topics.txt --seconds 40
"""
import argparse
import sys
import time

from app.jobs import store
from app.models import JobRequest
from app.pipeline import run_job


def main() -> int:
    ap = argparse.ArgumentParser(description="Qreate: topic -> publish-ready Qoneqt video")
    ap.add_argument("topic", nargs="?", help="Topic, prompt, idea or trend")
    ap.add_argument("--batch", help="Text file with one topic per line")
    ap.add_argument("--community", default="General")
    ap.add_argument("--language", default="english", choices=["english", "hinglish", "hindi"])
    ap.add_argument("--tone", default="energetic")
    ap.add_argument("--seconds", type=int, default=45)
    ap.add_argument("--style", default="mix", choices=["mix", "stock", "ai"])
    a = ap.parse_args()

    topics = [a.topic] if a.topic else []
    if a.batch:
        topics += [t.strip() for t in open(a.batch, encoding="utf-8") if t.strip()]
    if not topics:
        ap.error("Give a topic or --batch file")

    failures = 0
    for t in topics:
        req = JobRequest(topic=t, community=a.community, language=a.language, tone=a.tone,
                         target_seconds=a.seconds, visual_style=a.style)
        job = store.create(req)
        start = time.time()
        print(f"\n▶ {t}  (job {job['id']})")
        run_job(store, job["id"])
        j = store.get(job["id"])
        for k, st in j["stages"].items():
            print(f"   {st['status']:>8}  {st['label']:<32} {st.get('detail', '')}")
        if j["status"] == "failed":
            failures += 1
            print("   ERROR:", j["error"])
        else:
            print(f"   ✓ {j['outputs']['video']}  ({time.time() - start:.0f}s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
