"""Explicit local integration check using a user-supplied model and non-sensitive audio."""
import argparse
import json
from pathlib import Path
import time

from transcript_plus.service import Service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--language", default="en", choices=["en","zh",""])
    args = parser.parse_args()
    service = Service(args.data_dir)
    started = time.monotonic()
    try:
        service.dispatch("model.configure", {"path": args.model})
        project = service.import_media(args.audio)
        job_id = service.runner.enqueue(project["id"], args.language)["job_id"]
        while time.monotonic()-started < 300:
            job = next(j for j in service.store.jobs() if j["id"] == job_id)
            if job["status"] not in ("queued","running"):
                if job["status"] != "completed":
                    raise RuntimeError(job)
                project = service.store.project(project["id"])
                text = " ".join(s["text"] for s in project["transcript"]["segments"])
                report = {"status": job["status"], "elapsed_seconds": round(time.monotonic()-started,2),
                          "duration_ms": project["duration_ms"], "segments": len(project["transcript"]["segments"]),
                          "words": sum(len(s["words"]) for s in project["transcript"]["segments"]),
                          "text": text}
                for fmt in ("srt","vtt","txt","json"):
                    rendered = service.dispatch("export.render", {"project_id":project["id"],"expected_revision":project["revision"],"format":fmt})
                    Path(args.data_dir, f"smoke.{fmt}").write_text(rendered["content"], encoding="utf-8")
                print(json.dumps(report, ensure_ascii=False, indent=2))
                assert text, "No speech recognized; this smoke check needs audible speech."
                return
            time.sleep(.2)
        raise TimeoutError("ASR smoke check exceeded 300 seconds")
    finally:
        service.shutdown()


if __name__ == "__main__":
    main()
