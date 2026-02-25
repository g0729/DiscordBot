import logging
import subprocess
import sys
from pathlib import Path


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


def run() -> None:
    logger.info("yt-dlp 업데이트 시작")
    subprocess.run([sys.executable, "-m", "pip", "install", "yt-dlp", "--upgrade"], check=False, cwd=BASE_DIR)

    logger.info("기존 bot 프로세스 종료 시도")
    subprocess.run([sys.executable, "kill_bot.py"], check=False, cwd=BASE_DIR)

    logger.info("bot 재시작")
    subprocess.Popen(
        [sys.executable, "bot.py"],
        cwd=BASE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


if __name__ == "__main__":
    run()

