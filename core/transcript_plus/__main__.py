"""Versioned JSON Lines protocol on inherited stdio; never opens a network listener."""
import argparse
import json
from pathlib import Path
import sys

from .errors import AppError

MAX_REQUEST = 1024 * 1024


def serve(data_dir):
    from .service import Service
    from .instance import InstanceLock
    with InstanceLock(Path(data_dir)):
        service = Service(data_dir)
        try:
            while True:
                line = sys.stdin.buffer.readline(MAX_REQUEST+1)
                if not line:
                    break
                request_id = None
                try:
                    if len(line) > MAX_REQUEST:
                        raise AppError("REQUEST_TOO_LARGE", "操作資料過大。")
                    message = json.loads(line)
                    request_id = message.get("request_id")
                    if message.get("protocol_version") != 1 or not isinstance(message.get("params", {}), dict):
                        raise AppError("PROTOCOL_VERSION", "桌面與核心版本不相容。")
                    result = service.dispatch(message["method"], message.get("params", {}))
                    response = {"protocol_version": 1, "request_id": request_id, "result": result}
                except AppError as exc:
                    response = {"protocol_version": 1, "request_id": request_id, "error": exc.payload()}
                except (ValueError, KeyError, TypeError):
                    response = {"protocol_version": 1, "request_id": request_id, "error": {"code": "INVALID_INPUT", "message": "操作資料格式錯誤。"}}
                except OSError as exc:
                    response = {"protocol_version": 1, "request_id": request_id, "error": {"code": "DISK_FULL" if exc.errno == 28 else "FILE_ERROR", "message": "檔案無法讀寫，請檢查磁碟空間與存取權限。"}}
                except Exception as exc:
                    print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
                    response = {"protocol_version": 1, "request_id": request_id, "error": {"code": "INTERNAL_ERROR", "message": "處理失敗，請重新啟動程式。"}}
                print(json.dumps(response, ensure_ascii=False), flush=True)
                if len(line) > MAX_REQUEST:
                    break  # Do not interpret the remaining oversized payload as another command.
        finally:
            service.shutdown()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir")
    parser.add_argument("--worker")
    parser.add_argument("--diarize")
    args = parser.parse_args()
    if args.worker:
        from .processes import monitor_parent
        from .worker import main as worker_main
        monitor_parent()
        return worker_main(args.worker)
    if args.diarize:
        from .processes import monitor_parent
        from .worker import diarize_main
        monitor_parent()
        return diarize_main(args.diarize)
    if not args.data_dir:
        parser.error("--data-dir is required")
    serve(args.data_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
