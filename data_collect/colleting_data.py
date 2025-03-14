import base64
import json
import logging
import os
import re
import tempfile
import time
from logging.handlers import RotatingFileHandler
from operator import itemgetter
from typing import List

import requests
import yt_dlp
from dotenv import load_dotenv
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from tqdm import tqdm


# 로그 설정
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "colleting_data.log")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)

file_handler = RotatingFileHandler(
    log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)
logger.propagate = False

# 환경 변수 로드
load_dotenv()
youtube_cookies = os.environ.get("YOUTUBE_COOKIES", "")
KAKAO_API_KEY = os.getenv("KAKAO_API_KEY")
logger.info("환경 변수 로드 완료")

# LLM 초기화
# llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.1)
llm = ChatOpenAI(model_name="gpt-4o", temperature=0.1)
logger.info("LLM 초기화 완료")

with open("invalid_video.txt", "r", encoding="utf-8") as f:
    invalid_video_ids = f.read().splitlines()


# 쿠키 파일 생성 함수
def create_cookie_file(cookie_data_base64):
    if not cookie_data_base64:
        logger.warning("쿠키 데이터가 없습니다. 쿠키 없이 진행합니다.")
        return None

    try:
        # base64로 인코딩된 쿠키 문자열을 디코딩
        cookie_data = base64.b64decode(cookie_data_base64).decode("utf-8")
        logger.debug("쿠키 데이터 디코딩 완료")

        # 쿠키가 JSON 형식인지 확인하고 Netscape 형식으로 변환
        try:
            # JSON 형식인지 확인
            json_cookies = json.loads(cookie_data)
            logger.debug("JSON 형식 쿠키 감지됨, Netscape 형식으로 변환")

            # Netscape 형식으로 변환
            netscape_cookies = "# Netscape HTTP Cookie File\n"
            for cookie in json_cookies:
                if all(k in cookie for k in ["domain", "path", "name", "value"]):
                    secure = "TRUE" if cookie.get("secure", False) else "FALSE"
                    http_only = "TRUE" if cookie.get("httpOnly", False) else "FALSE"
                    expires = str(int(cookie.get("expirationDate", 0)))
                    netscape_cookies += f"{cookie['domain']}\tTRUE\t{cookie['path']}\t{secure}\t{expires}\t{cookie['name']}\t{cookie['value']}\n"

            cookie_data = netscape_cookies
        except json.JSONDecodeError:
            # 이미 Netscape 형식이거나 다른 형식인 경우 그대로 사용
            logger.debug("쿠키가 JSON 형식이 아닙니다. 원본 형식 유지")
            pass

        # 임시 파일 생성
        cookie_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        cookie_file.write(cookie_data.encode("utf-8"))
        cookie_file.close()
        logger.info(f"쿠키 파일 생성 완료: {cookie_file.name}")

        return cookie_file.name
    except Exception as e:
        logger.error(f"쿠키 파일 생성 중 오류 발생: {str(e)}")
        return None


# 플레이리스트 정보 가져오기 (쿠키 파일 사용)
# def get_playlist_info(playlist_url, cookie_file_path=None):
#     logger.info(f"플레이리스트 정보 가져오기 시작: {playlist_url}")
#     ydl_opts = {
#         "quiet": True,
#         "no_warnings": True,
#         "extract_flat": True,  # 기본 정보만 추출하도록 변경
#         "nocheckcertificate": True,
#         "ignoreerrors": True,
#         "no_color": True,
#         "socket_timeout": 30,  # 소켓 타임아웃 설정
#         "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
#     }

#     # 쿠키 파일이 있으면 옵션에 추가
#     if cookie_file_path:
#         ydl_opts["cookiefile"] = cookie_file_path
#         logger.info(f"쿠키 파일 사용")

#     try:
#         with yt_dlp.YoutubeDL(ydl_opts) as ydl:
#             logger.info("YouTube 데이터 추출 중...")
#             playlist_info = ydl.extract_info(playlist_url, download=False)
#             logger.info(f"총 {len(playlist_info.get('entries', []))}개 영상")
#             return playlist_info
#     except Exception as e:
#         logger.error(f"플레이리스트 정보 추출 중 오류 발생: {str(e)}")
#         return None


# 플레이리스트 정보 가져오기 (chrome 브라우저 쿠키 사용)
def get_playlist_info(playlist_url, use_browser_cookies=True):
    logger.info(f"플레이리스트 정보 가져오기 시작: {playlist_url}")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,  # 기본 정보만 추출하도록 변경
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "no_color": True,
        "socket_timeout": 30,  # 소켓 타임아웃 설정
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    }

    # 쿠키 파일이 있으면 옵션에 추가
    if use_browser_cookies:
        ydl_opts["cookiesfrombrowser"] = ("chrome",)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info("YouTube 데이터 추출 중...")
            playlist_info = ydl.extract_info(playlist_url, download=False)
            logger.info(f"총 {len(playlist_info.get('entries', []))}개 영상")
            return playlist_info
    except Exception as e:
        logger.error(f"플레이리스트 정보 추출 중 오류 발생: {str(e)}")
        return None


# # 개별 비디오 정보 가져오기 (쿠키 파일 사용)
# def get_video_info(video_id, cookie_file_path=None):
#     logger.info(f"비디오 정보 가져오기 시작: {video_id}")
#     video_url = f"https://www.youtube.com/watch?v={video_id}"

#     ydl_opts = {
#         "quiet": True,
#         "no_warnings": True,
#         "nocheckcertificate": True,
#         "ignoreerrors": True,
#         "no_color": True,
#         "socket_timeout": 30,
#         "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
#     }

#     if cookie_file_path:
#         ydl_opts["cookiefile"] = cookie_file_path


#     try:
#         with yt_dlp.YoutubeDL(ydl_opts) as ydl:
#             logger.info(f"비디오 정보 추출 완료...")
#             return ydl.extract_info(video_url, download=False)
#     except Exception as e:
#         logger.error(f"비디오 정보 추출 중 오류 발생: {str(e)}")
#         return None


# 개별 비디오 정보 가져오기 (chrome 브라우저 쿠키 사용)
def get_video_info(video_id, use_browser_cookies=True):
    logger.info(f"비디오 정보 가져오기 시작: {video_id}")
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    # 기본 옵션 설정
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "no_color": True,
        "socket_timeout": 30,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    }

    # 브라우저 쿠키 사용 설정
    if use_browser_cookies:
        ydl_opts["cookiesfrombrowser"] = ("chrome",)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(f"비디오 정보 추출 완료...")
            return ydl.extract_info(video_url, download=False)
    except Exception as e:
        logger.error(f"비디오 정보 추출 중 오류 발생: {str(e)}")
        return None


def extract_restaurant_info(description):
    """
    설명에서 식당 정보(이름과 주소)를 추출하는 함수
    단일 식당 또는 여러 식당 정보를 모두 처리할 수 있음
    """
    # 식당 정보 구분자 패턴 (예: [도화], [오픈마켓] 등)
    section_pattern = r"^\[(.*?)\]"
    sections = re.findall(section_pattern, description, re.MULTILINE)

    # 여러 식당 정보가 있는 경우
    if len(sections) > 1:
        restaurants = []

        # 설명 텍스트를 줄 단위로 분리
        lines = description.split("\n")
        current_section = None
        current_info = {"name": None, "address": None}

        for line in lines:
            # 새로운 섹션 시작 확인
            section_match = re.match(section_pattern, line)
            if section_match:
                # 이전 섹션 정보가 있으면 저장
                if current_section and current_info["name"] and current_info["address"]:
                    restaurants.append(current_info.copy())

                # 새 섹션 시작
                current_section = section_match.group(1).strip()
                current_info = {"name": current_section, "address": None}

            # 주소 패턴 확인
            address_match = re.match(
                r"^(서울|경기|인천|부산|대구|대전|광주|울산|세종|강원|충북|충남|전북|전남|경북|경남|제주).*?$",
                line,
            )
            if address_match and current_section:
                current_info["address"] = line.strip()

        # 마지막 섹션 정보 저장
        if current_section and current_info["name"] and current_info["address"]:
            restaurants.append(current_info.copy())

        return restaurants if restaurants else []

    # 단일 식당 정보만 있는 경우
    else:
        # 가게명 추출 패턴: [가게명] 또는 첫 줄
        name_pattern = r"^\[(.*?)\]|^(.+?)$"
        name_match = re.search(name_pattern, description, re.MULTILINE)

        # 주소 추출 패턴: 서울, 경기, 인천 등으로 시작하거나 특정 패턴의 주소
        address_pattern = r"^(서울|경기|인천|부산|대구|대전|광주|울산|세종|강원|충북|충남|전북|전남|경북|경남|제주).*?$"
        address_match = re.search(address_pattern, description, re.MULTILINE)

        name = None
        address = None

        if name_match:
            # 대괄호 안의 내용이 있으면 그것을 사용, 없으면 첫 번째 그룹 사용
            name = name_match.group(1) if name_match.group(1) else name_match.group(2)
            name = name.strip()

        if address_match:
            address = address_match.group(0).strip()

        if name and address:
            return [{"name": name, "address": address}]
        return []


# 메뉴 정보를 나타내는 클래스
class Menu(BaseModel):
    menu_type: str = Field(..., description="메뉴의 종류: 예) 양식, 일식, 한식 등")
    menu_name: str = Field(..., description="메뉴명")
    menu_review: str = Field(..., description="메뉴에 대한 짧은 후기")


# 식당의 메뉴 리스트를 나타내는 클래스
class RestaurantInfo(BaseModel):
    restaurant_name: str = Field(..., description="식당 이름")
    menus: List[Menu] = Field(..., description="이 식당의 모든 메뉴 정보 리스트")


# 여러 식당 정보를 위한 클래스
class MultipleRestaurantInfo(BaseModel):
    restaurants: List[RestaurantInfo] = Field(..., description="여러 식당 정보 리스트")


# 여러 식당 정보를 추출하는 함수
def extract_multiple_restaurant_info(description):
    """여러 식당 정보를 추출하는 함수"""
    section_pattern = r"^\[(.*?)\]"
    sections = re.findall(section_pattern, description, re.MULTILINE)

    # 구분자가 없거나 하나만 있는 경우 기존 방식 사용
    if len(sections) <= 1:
        name, address = extract_restaurant_info(description)
        if name and address:
            return [{"name": name, "address": address}]
        return []

    # 여러 식당 정보가 있는 경우
    restaurants = []

    # 설명 텍스트를 줄 단위로 분리
    lines = description.split("\n")
    current_section = None
    current_info = {"name": None, "address": None}

    for line in lines:
        # 새로운 섹션 시작 확인
        section_match = re.match(section_pattern, line)
        if section_match:
            # 이전 섹션 정보가 있으면 저장
            if current_section and current_info["name"] and current_info["address"]:
                restaurants.append(current_info.copy())

            # 새 섹션 시작
            current_section = section_match.group(1).strip()
            current_info = {"name": current_section, "address": None}

        # 주소 패턴 확인
        address_match = re.match(
            r"^(서울|경기|인천|부산|대구|대전|광주|울산|세종|강원|충북|충남|전북|전남|경북|경남|제주).*?$",
            line,
        )
        if address_match and current_section:
            current_info["address"] = line.strip()

    # 마지막 섹션 정보 저장
    if current_section and current_info["name"] and current_info["address"]:
        restaurants.append(current_info.copy())

    return restaurants


# 여러 식당 정보를 처리하는 프롬프트
prompt = PromptTemplate.from_template(
    """다음은 성시경의 먹을텐데 유튜브 영상의 스크립트입니다. 
이 영상에는 여러 식당이 등장할 수 있습니다. 스크립트를 읽고 아래의 형식으로 모든 데이터를 한글로 추출해주세요.
                                      
SCRIPT:
{script}

### 식당 정보
{restaurant_info}

### 주의사항
1. 성시경이 실제로 먹은 메뉴를 정리하세요.(문맥상 단순 언급은 제외)
2. 메뉴들을 주메뉴와 건더기, 반찬 등으로 구분 하세요.
3. 반찬과 건더기는 해당 메인메뉴의 리뷰에 포함시키세요.
4. 메뉴의 종류는 언급된 메뉴에 맞는 카테고리를 적합하게 작성해주세요.
5. 여러 식당이 있는 경우, 각 식당별로 메뉴를 구분하여 정리하세요.
6. 스크립트에서 각 식당에 해당하는 부분만 추출하여 정리하세요.

OUTPUT_FORMAT:
[
  {{
    "restaurant_name": "첫 번째 식당 이름",
    "menus": [
      {{
        "menu_type": "메뉴의 종류 (예: 양식, 일식, 한식 등)",
        "menu_name": "메뉴명",
        "menu_review": "영상에 언급된 해당 메뉴에 대한 성시경이 느낀점과 자연스러운 설명"
      }},
      ...
    ]
  }},
  {{
    "restaurant_name": "두 번째 식당 이름",
    "menus": [
      {{
        "menu_type": "메뉴의 종류",
        "menu_name": "메뉴명",
        "menu_review": "메뉴 후기"
      }},
      ...
    ]
  }},
  ...
]
"""
)


parser = JsonOutputParser(pydantic_object=MultipleRestaurantInfo)

# 체인 설정
chain = (
    {"script": itemgetter("script"), "restaurant_info": itemgetter("restaurant_info")}
    | prompt
    | llm
    | parser
)

# JSON 파일 경로 설정
json_file_path = "meokten_restaurants.json"

# 기존 JSON 파일 로드 (있는 경우)
all_restaurants = {}
if os.path.exists(json_file_path):
    try:
        with open(json_file_path, "r", encoding="utf-8") as f:
            all_restaurants = json.load(f)
        logger.info(f"기존 JSON 파일에서 {len(all_restaurants)} 개의 식당 정보 로드")
    except Exception as e:
        logger.error(f"기존 JSON 파일 로드 중 오류: {str(e)}")
        all_restaurants = {}

# 이미 처리된 비디오 ID 목록 (JSON에서 추출)
processed_videos = []
for key in all_restaurants.keys():
    # video_id_i 형식에서 video_id 부분만 추출
    if "_" in key:
        video_id = key[:-2]
        if video_id not in processed_videos:
            processed_videos.append(video_id)
    else:
        processed_videos.append(key)  # 기존 형식 지원

logger.info(f"이미 처리된 비디오 수: {len(processed_videos)}")


# Kakao Geocoding API 요청
coordinate_url = "https://dapi.kakao.com/v2/local/search/address.json"
station_url = "https://dapi.kakao.com/v2/local/search/category.json"
headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
logger.info("Kakao API 설정 완료")

# 특정 재생목록 URL
playlist_url = (
    "https://www.youtube.com/playlist?list=PLuMuHAJh9g_Py_PSm8gmHdlcil6CQ9QCM"
)

logger.info("쿠키 파일 생성 중...")
cookie_file_path = create_cookie_file(youtube_cookies) if youtube_cookies else None

# 플레이리스트 정보 가져오기 (extract_flat=True로 기본 정보만 가져옴)
playlist_info = get_playlist_info(playlist_url, cookie_file_path)

if not playlist_info:
    logger.error("플레이리스트 정보를 가져오지 못했습니다.")
    if cookie_file_path and os.path.exists(cookie_file_path):
        os.unlink(cookie_file_path)
    exit(1)

total_videos = len(playlist_info.get("entries", []))
processed_count = 0
skipped_count = 0
error_count = 0

logger.info(f"총 {total_videos}개 영상 처리 시작")


# 자막 추출 함수 추가
def get_transcript_with_cookies(video_id, cookie_file_path=None):
    """yt-dlp를 사용하여 자막을 추출하는 함수"""
    options = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["ko", "en"],
        "quiet": True,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    }

    if cookie_file_path:
        options["cookiefile"] = cookie_file_path

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False
            )

            # 자막 정보 추출
            subtitles = info.get("subtitles", {})
            auto_captions = info.get("automatic_captions", {})

            # 1. 일반 자막 확인 (live_chat이 아닌 것만)
            has_only_live_chat = True  # live_chat만 있는지 확인하는 플래그
            subtitles_list = list(subtitles.keys())
            if "live_chat" in subtitles_list:
                subtitles_list.remove("live_chat")
            if subtitles_list:
                has_only_live_chat = False
                lang = subtitles_list[0]
                url = subtitles[lang][0]["url"]
                try:
                    response = requests.get(url)
                    if response.status_code == 200:
                        transcript_text = convert_vtt_to_text(response.json())
                        if transcript_text:
                            logger.info(f"일반 자막({lang}) 추출 완료")
                            return transcript_text
                except Exception as e:
                    logger.warning(f"일반 자막({lang}) 변환 중 오류: {str(e)}")
            # 2. live_chat만 있는 경우 자동 생성 자막 시도 (한국어만)
            if has_only_live_chat and "ko" in auto_captions:
                logger.info("일반 자막이 live_chat뿐이므로 자동 생성 자막(ko) 시도")
                for caption in auto_captions["ko"]:
                    if caption.get("ext") == "json3":
                        url = caption["url"]
                        try:
                            response = requests.get(url)
                            if response.status_code == 200:
                                transcript_text = convert_vtt_to_text(response.json())
                                if transcript_text:
                                    logger.info(f"자동 생성 자막(ko) 추출 완료")
                                    return transcript_text
                        except Exception as e:
                            logger.warning(f"자동 생성 자막(ko) 변환 중 오류: {str(e)}")

            # 자막을 찾지 못한 경우
            logger.warning("사용 가능한 자막을 찾지 못했습니다")
            return None

    except Exception as e:
        logger.error(f"yt-dlp로 자막 추출 중 오류 발생: {str(e)}")
        return None


def convert_vtt_to_text(response):
    """VTT 형식의 자막을 일반 텍스트로 변환"""
    # 타임스탬프 및 VTT 헤더 제거
    text_lines = []

    try:
        for event in response.get("events", []):
            if "segs" in event and event["segs"]:
                raw_text = ""
                for seg in event["segs"]:
                    if "utf8" in seg and seg["utf8"].strip():
                        raw_text += seg["utf8"].strip()
                text_lines.append(raw_text)

        result = "\n".join(text_lines)
        if not result.strip():
            logger.warning("자막 변환 결과가 비어 있습니다")
            return None

        logger.info(f"자막 변환 완료: {len(result)} 글자")
        return result
    except Exception as e:
        logger.error(f"자막 변환 중 오류 발생: {str(e)}")
        return None


def get_coordinates_from_address(address, headers, coordinate_url):
    """주소로부터 좌표를 추출하는 함수 (여러 방법 시도)"""
    latitude = longitude = "정보 없음"

    # 1. 원본 주소로 시도
    logger.info(f"원본 주소로 좌표 검색 시도: {address}")
    params = {"query": address}
    response = requests.get(coordinate_url, headers=headers, params=params)

    if response.status_code == 200:
        data = response.json()
        if data["documents"]:
            location = data["documents"][0]
            latitude = location["y"]
            longitude = location["x"]
            logger.info(
                f"원본 주소로 위치 정보 추출 완료: 위도 {latitude}, 경도 {longitude}"
            )
            return latitude, longitude

    # 2. 괄호 제거 주소로 시도
    if "(" in address:
        address_2 = address.split("(")[0].strip()
        logger.info(f"괄호 제거 주소로 좌표 검색 시도: {address_2}")
        params = {"query": address_2}
        response = requests.get(coordinate_url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            if data["documents"]:
                location = data["documents"][0]
                latitude = location["y"]
                longitude = location["x"]
                logger.info(
                    f"괄호 제거 주소로 위치 정보 추출 완료: 위도 {latitude}, 경도 {longitude}"
                )
                return latitude, longitude
    else:
        address_2 = address

    # 3. 마지막 단어 제거 시도 (최대 2회)
    address_parts = address_2.split(" ")

    for i in range(1, min(3, len(address_parts))):
        if len(address_parts) <= i:
            break

        address_3 = " ".join(address_parts[:-i])
        logger.info(f"단어 {i}개 제거 주소로 좌표 검색 시도: {address_3}")
        params = {"query": address_3}
        response = requests.get(coordinate_url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            if data["documents"]:
                location = data["documents"][0]
                latitude = location["y"]
                longitude = location["x"]
                logger.info(
                    f"단어 {i}개 제거 주소로 위치 정보 추출 완료: 위도 {latitude}, 경도 {longitude}"
                )
                return latitude, longitude

    # 모든 시도 실패
    logger.warning(f"모든 방법으로 좌표 검색 실패: {address}")
    return latitude, longitude


# 각 비디오 처리
for entry in tqdm(playlist_info.get("entries", []), desc="처리 중"):
    # 기본 정보만 있는 경우 (extract_flat=True)
    video_id = entry.get("id", "")
    if video_id in invalid_video_ids:
        logger.info(f"무효한 비디오입니다: {video_id}")
        skipped_count += 1
        continue
    video_title = entry.get("title", "제목 없음")
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    logger.info(f"처리 중: {video_title} ({video_id})")

    # 이미 처리된 비디오 건너뛰기
    if video_id in processed_videos:
        skip_reason = f"이미 처리된 영상입니다: {video_id}"
        logger.info(skip_reason)
        skipped_count += 1
        continue

    # 개별 비디오 정보 가져오기 (상세 정보)
    try:
        # 비디오 정보 가져오기 전에 잠시 대기 (YouTube 서버 부하 방지)
        time.sleep(1)
        # video_info = get_video_info(video_id, cookie_file_path)
        video_info = get_video_info(video_id, use_browser_cookies=False)

        if not video_info:
            error_reason = f"비디오 정보를 가져오지 못했습니다: {video_id}"
            logger.error(error_reason)
            error_count += 1
            continue

        description = video_info.get("description", "")

        # #shorts 필터링
        if "#shorts" in description:
            skip_reason = f"Shorts 영상은 건너뜁니다: {video_id}"
            logger.info(skip_reason)
            skipped_count += 1
            continue

        # 정규표현식으로 가게명과 주소 추출
        restaurants = extract_restaurant_info(description)

        if not restaurants:
            error_reason = f"가게명 또는 주소를 추출할 수 없습니다: {video_id}"
            logger.warning(error_reason)
            error_count += 1
            continue

        logger.info(f"{len(restaurants)}개 식당 정보 추출 완료")

        # 자막 가져오기
        script = []
        try:
            logger.info(f"자막 추출 시작: {video_id}")

            # yt-dlp로 시도
            script_text = get_transcript_with_cookies(video_id, cookie_file_path)

            if script_text:
                script = script_text
                logger.info(f"자막 추출 완료: {len(script)} 글자")
            else:
                error_reason = "자막을 추출할 수 없습니다."
                logger.error(error_reason)
                error_count += 1
                continue

            # 여러 식당 정보 처리

            restaurant_info_str = "\n".join(
                [f"식당명: {r['name']}, 주소: {r['address']}" for r in restaurants]
            )
            # 데이터 구성 (LLM 입력용)
            # 메뉴 정보 추출
            logger.info("LLM을 사용하여 식당의 메뉴 정보 추출 중...")
            data = {"script": script, "restaurant_info": restaurant_info_str}
            result = chain.invoke(data)
            logger.info(f"여러 식당의 메뉴 정보 추출 완료: {len(result)}개 식당")
            # 각 식당 정보 처리
            for i, restaurant_info in enumerate(result):
                if i < len(restaurants):  # 안전 검사
                    logger.info(
                        f"식당 정보 처리 중: {restaurant_info['restaurant_name']}"
                    )
                    restaurant_name = restaurant_info["restaurant_name"]
                    restaurant_address = restaurants[i]["address"]

                    # 좌표 검색
                    latitude, longitude = get_coordinates_from_address(
                        restaurant_address, headers, coordinate_url
                    )
                    station_name = "정보 없음"
                    station_distance = "정보 없음"

                    try:
                        # 지하철역 검색
                        params = {
                            "category_group_code": "SW8",
                            "x": longitude,
                            "y": latitude,
                            "radius": 2000,
                            "sort": "distance",
                        }

                        response = requests.get(
                            station_url, headers=headers, params=params
                        )
                        if response.status_code == 200:
                            data = response.json()
                            if data["documents"]:
                                station_name = data["documents"][0]["place_name"]
                                station_distance = data["documents"][0]["distance"]
                    except Exception as e:
                        logger.error(f"지하철역 검색 중 오류 발생: {str(e)}")

                    # JSON 데이터 구성
                    restaurant_data = {
                        "restaurant_name": restaurant_name,
                        "address": restaurant_address,
                        "latitude": latitude,
                        "longitude": longitude,
                        "station_name": f"{station_name}({station_distance}m)",
                        "video_url": video_url,
                        "menus": restaurant_info["menus"],
                    }

                    # 전체 식당 목록에 추가 (video_id + 인덱스를 키로 사용)
                    all_restaurants[f"{video_id}_{i}"] = restaurant_data

            # 변경사항 즉시 저장
            with open(json_file_path, "w", encoding="utf-8") as f:
                json.dump(all_restaurants, f, ensure_ascii=False, indent=2)

            logger.info(f"'{video_title}' 정보 저장 완료 (JSON)")
            processed_count += 1

        except Exception as e:
            error_reason = f"자막을 가져오는 중 오류 발생: {str(e)}"
            logger.error(error_reason)
            error_count += 1

    except Exception as e:
        error_reason = f"비디오 처리 중 오류 발생: {str(e)}"
        logger.error(error_reason)
        error_count += 1
        # 잠시 대기 후 계속 진행
        time.sleep(5)

# 임시 쿠키 파일 삭제
if cookie_file_path and os.path.exists(cookie_file_path):
    os.unlink(cookie_file_path)
    logger.info("임시 쿠키 파일 삭제 완료")


logger.info(
    f"작업 완료: 총 {total_videos}개 중 {processed_count}개 처리, {skipped_count}개 건너뜀, {error_count}개 오류"
)
logger.info(
    f"총 {len(all_restaurants)}개의 식당 정보가 {json_file_path}에 저장되었습니다."
)
