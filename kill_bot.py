import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
PID_FILE_PATH = BASE_DIR / "bot.pid"


def get_pid_from_file() -> Optional[int]:
    if not PID_FILE_PATH.exists():
        return None

    try:
        pid_text = PID_FILE_PATH.read_text(encoding="utf-8").strip()
        return int(pid_text)
    except (ValueError, OSError):
        return None


def is_expected_bot_process(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return False

    cmd = result.stdout.strip().lower()
    return "python" in cmd and "bot.py" in cmd


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def kill_bot_processes() -> int:
    pid = get_pid_from_file()
    if pid is None:
        logger.info("PID 파일이 없어 종료할 bot 프로세스를 찾지 못했습니다.")
        return 0

    if not is_expected_bot_process(pid):
        logger.warning("PID 파일의 프로세스가 bot.py가 아니거나 이미 종료됨 (pid=%s). PID 파일 정리.", pid)
        PID_FILE_PATH.unlink(missing_ok=True)
        return 0

    try:
        os.kill(pid, signal.SIGTERM)
        logger.info("SIGTERM 전송 (pid=%s)", pid)
    except ProcessLookupError:
        PID_FILE_PATH.unlink(missing_ok=True)
        return 0

    for _ in range(10):
        if not process_exists(pid):
            PID_FILE_PATH.unlink(missing_ok=True)
            logger.info("프로세스 정상 종료 (pid=%s)", pid)
            return 1
        time.sleep(0.2)

    try:
        os.kill(pid, signal.SIGKILL)
        logger.warning("SIGTERM 응답 없음, SIGKILL 전송 (pid=%s)", pid)
    except ProcessLookupError:
        pass

    PID_FILE_PATH.unlink(missing_ok=True)
    return 1


if __name__ == "__main__":
    count = kill_bot_processes()
    print(f"killed={count}")

