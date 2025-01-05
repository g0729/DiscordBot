import os
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys

# 환경 변수에서 로그인 정보 로드
YOUTUBE_EMAIL = os.environ.get("YOUTUBE_EMAIL", "your_email@example.com")
YOUTUBE_PASSWORD = os.environ.get("YOUTUBE_PASSWORD", "your_password")

# Headless Chrome 옵션 설정
chrome_options = Options()
# chrome_options.add_argument("--headless")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--window-size=1920,1080")

driver = webdriver.Chrome(options=chrome_options)

try:
    # YouTube 접속
    driver.get("https://www.youtube.com/")

    time.sleep(2)

    # 로그인 버튼 클릭 (우측 상단 로그인 버튼)
    # 언어/환경에 따라 버튼의 text나 위치가 다를 수 있으므로 적절히 수정 필요
    signin_button = driver.find_element(By.XPATH, '//tp-yt-paper-button[@aria-label="Sign in"]')
    signin_button.click()

    time.sleep(3)

    # 구글 로그인 페이지로 리다이렉트 됨
    # 이메일 입력
    email_input = driver.find_element(By.XPATH, '//input[@type="email"]')
    email_input.send_keys(YOUTUBE_EMAIL)
    email_input.send_keys(Keys.ENTER)

    time.sleep(3)

    # 비밀번호 입력
    password_input = driver.find_element(By.XPATH, '//input[@type="password"]')
    password_input.send_keys(YOUTUBE_PASSWORD)
    password_input.send_keys(Keys.ENTER)

    time.sleep(5)

    # 로그인 완료 후 메인페이지나 계정이미지 확인 등으로 로그인 성공 여부 판단 가능
    # 여기서는 단순 대기
    time.sleep(5)

    # 쿠키 추출
    cookies = driver.get_cookies()

finally:
    driver.quit()

# yt-dlp 호환 cookies.txt 포맷으로 저장
# Netscape HTTP Cookie File format
cookies_txt_path = "cookies.txt"
with open(cookies_txt_path, "w", encoding="utf-8") as f:
    f.write("# Netscape HTTP Cookie File\n")
    for cookie in cookies:
        # cookie['domain'], 'TRUE'/'FALSE', cookie['path'], 'TRUE'/'FALSE'(https여부), cookie['expiry'], cookie['name'], cookie['value']
        # expiry가 없을 경우 처리 필요
        expiry = str(int(cookie["expiry"])) if "expiry" in cookie else "0"
        secure_flag = "TRUE" if cookie.get("secure", False) else "FALSE"
        # HTTPOnly 쿠키 확인
        # yt-dlp 가이드에 따르면 별도의 필드는 필요하지 않고 httpOnly 설정여부는 파일포맷에 직접적 영향 없음
        f.write(
            f"{cookie['domain']}\t"
            f"{'TRUE' if cookie['domain'].startswith('.') else 'FALSE'}\t"
            f"{cookie['path']}\t"
            f"{secure_flag}\t"
            f"{expiry}\t"
            f"{cookie['name']}\t"
            f"{cookie['value']}\n"
        )
print(f"Cookies saved to {cookies_txt_path}")

# 이제 yt-dlp를 다음과 같이 사용할 수 있습니다.
# yt-dlp --cookies cookies.txt "https://www.youtube.com/watch?v=VIDEO_ID"
