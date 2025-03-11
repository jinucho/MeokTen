# app.py
import streamlit as st
from agent.graph import run_agent, create_agent_graph
from utils.map_utils import display_map_in_streamlit, create_restaurant_map
from streamlit_folium import folium_static
import os
from dotenv import load_dotenv
import logging
import argparse
from typing import Any, Dict, List

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 현재 작업 디렉토리 및 파일 확인
current_dir = os.getcwd()
logger.info(f"현재 작업 디렉토리: {current_dir}")

# 데이터베이스 파일 경로 확인
db_path = os.path.join(os.path.dirname(current_dir), "meokten.db")
if os.path.exists(db_path):
    logger.info(f"데이터베이스 파일 존재: {db_path}")
else:
    logger.warning(f"데이터베이스 파일 없음: {db_path}")

# 다른 가능한 경로 확인
db_path = os.path.join(current_dir, "meokten.db")
if os.path.exists(db_path):
    logger.info(f"현재 디렉토리에 데이터베이스 파일 존재: {db_path}")
else:
    logger.warning(f"현재 디렉토리에도 데이터베이스 파일 없음: {db_path}")
    # meokten 디렉토리 내부 확인
    db_path = os.path.join(current_dir, "meokten.db")
    if os.path.exists(db_path):
        logger.info(f"meokten 디렉토리에 데이터베이스 파일 존재: {db_path}")
    else:
        logger.warning(f"meokten 디렉토리에도 데이터베이스 파일 없음: {db_path}")

# 환경 변수 로드
load_dotenv()

# 명령줄 인수 파싱
parser = argparse.ArgumentParser(description="MeokTen 앱 실행")
parser.add_argument("--db_path", type=str, help="데이터베이스 파일 경로")
args, unknown = parser.parse_known_args()

# 데이터베이스 경로 설정
db_path = args.db_path if args.db_path else None

# 페이지 설정
st.set_page_config(page_title="먹튼 - 맛집 추천 AI", page_icon="🍽️", layout="wide")

# 그래프를 세션 상태에 저장 (최초 접속 시 1회만 생성)
if "agent_graph" not in st.session_state:
    logger.info("에이전트 그래프 초기화")
    st.session_state.agent_graph = create_agent_graph()
    logger.info("에이전트 그래프 초기화 완료")

# 자바스크립트 코드 추가 (이벤트 리스너, 자동 스크롤)
st.markdown(
    """
    <script>
    // 메시지 이벤트 리스너 설정
    window.addEventListener('message', function(e) {
        if (e.data && e.data.type === 'highlight_restaurant') {
            // URL 파라미터 설정하여 페이지 리로드
            const url = new URL(window.location.href);
            url.searchParams.set('restaurant_id', e.data.id);
            window.location.href = url.toString();
        }
    });
    
    // 자동 스크롤 함수
    function scrollChatToBottom() {
        var chatContainer = document.querySelector('[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlock"]');
        if (chatContainer) {
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
    }
    // 페이지 로드 후 스크롤
    window.addEventListener('load', scrollChatToBottom);
    // 1초마다 스크롤 (새 메시지가 추가될 때)
    setInterval(scrollChatToBottom, 1000);
    </script>
    """,
    unsafe_allow_html=True,
)

# 제목 및 소개
st.title("🍽️ 먹튼 - 맛집 추천 AI")
st.subheader("성시경의 '먹을텐데' 맛집 추천 서비스")
st.markdown(
    """
    성시경이 유튜브 채널 '먹을텐데'에서 소개한 맛집을 추천해드립니다.
    지역, 음식 종류 등을 입력하시면 맞춤형 맛집을 추천해드립니다.
    """
)

# 사이드바
with st.sidebar:
    st.title("🍽️ 먹튼")
    st.markdown("### 맛집 추천 AI 어시스턴트")
    st.markdown("---")
    st.markdown(
        """
        ### 사용 방법
        1. 원하는 맛집 정보를 질문하세요
        2. AI가 맛집을 추천해드립니다
        3. 식당 이름을 클릭하면 상세 정보를 볼 수 있습니다
        
        ### 예시 질문
        - 논현역 맛집 추천해줘
        - 강남에 있는 한식 맛집 알려줘
        - 성시경이 추천한 분식집 어디 있어?
        - 서울 중구에 있는 맛집 알려줘
        """
    )
    st.markdown("---")
    st.markdown("© 2023 먹튼")
    st.markdown("데이터 출처: 성시경의 '먹을텐데' 유튜브 채널")

# 메인 컨텐츠
# 채팅 기록 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.restaurants = []
    st.session_state.highlighted_restaurant = None  # 하이라이트할 식당 ID


# 식당 하이라이트 함수
def highlight_restaurant(restaurant_id):
    """식당을 하이라이트하는 함수"""
    st.session_state.highlighted_restaurant = restaurant_id
    st.rerun()


# 좌우 컬럼 생성
left_col, right_col = st.columns([1, 1])

# 왼쪽 컬럼: 지도 표시
with left_col:
    st.header("🗺️ 맛집 지도")

    # 지도 표시 (식당 정보가 있는 경우)
    if "restaurants" in st.session_state and st.session_state.restaurants:
        # 디버깅 정보는 별도 체크박스로 분리
        if st.checkbox("지도 디버깅 정보", value=False):
            st.write("### 좌표 정보")
            for i, r in enumerate(st.session_state.restaurants):
                st.write(
                    f"{i+1}. {r.get('name')}: 위도={r.get('latitude')}, 경도={r.get('longitude')}"
                )

        # 유효한 좌표가 있는 식당 필터링
        valid_restaurants = []
        for restaurant in st.session_state.restaurants:
            try:
                lat = restaurant.get("latitude")
                lng = restaurant.get("longitude")

                # 문자열인 경우 변환 시도
                if isinstance(lat, str) and lat not in ["정보 없음", "0", ""]:
                    lat = float(lat)
                if isinstance(lng, str) and lng not in ["정보 없음", "0", ""]:
                    lng = float(lng)

                # 유효한 좌표인 경우만 추가
                if lat and lng and lat != 0 and lng != 0:
                    valid_restaurants.append(restaurant)
            except (ValueError, TypeError) as e:
                logger.warning(
                    f"좌표 변환 오류: {str(e)}, 식당: {restaurant.get('name', '이름 없음')}"
                )
                continue

        # 유효한 식당이 있는 경우 지도 생성
        if valid_restaurants:
            # 하이라이트된 식당 ID 가져오기
            highlighted_id = st.session_state.get("highlighted_restaurant")

            # 중심 좌표 계산
            center = None
            if highlighted_id:
                for r in valid_restaurants:
                    if str(r.get("id", "")) == str(highlighted_id):
                        try:
                            center = [
                                float(r.get("latitude")),
                                float(r.get("longitude")),
                            ]
                            break
                        except (ValueError, TypeError):
                            pass

            if not center and valid_restaurants:
                try:
                    center_lat = float(valid_restaurants[0].get("latitude", 37.5665))
                    center_lng = float(valid_restaurants[0].get("longitude", 126.9780))
                    center = [center_lat, center_lng]
                except (ValueError, TypeError):
                    center = [37.5665, 126.9780]  # 기본값: 서울
            else:
                center = [37.5665, 126.9780]  # 기본값: 서울

            # 지도 생성 및 표시
            st.info(f"총 {len(valid_restaurants)}개의 식당을 지도에 표시합니다.")
            m = create_restaurant_map(
                valid_restaurants,
                center=center,
                highlighted_id=highlighted_id,
                map_style="기본",
                use_clustering=True,
            )
            folium_static(m)
            st.caption(f"총 {len(valid_restaurants)}개의 식당이 지도에 표시되었습니다.")
        else:
            st.warning("표시할 유효한 좌표 정보가 없습니다.")
            # 빈 지도 표시 (서울 중심)
            empty_map = create_restaurant_map([], center=[37.5665, 126.9780])
            folium_static(empty_map)
    else:
        st.info("검색 결과가 지도에 표시됩니다.")
        # 빈 지도 표시 (서울 중심)
        empty_map = create_restaurant_map([], center=[37.5665, 126.9780])
        folium_static(empty_map)

    # 식당 목록 표시 (접을 수 있는 섹션)
    if "restaurants" in st.session_state and st.session_state.restaurants:
        with st.expander("📋 검색된 식당 목록", expanded=False):
            for i, restaurant in enumerate(st.session_state.restaurants, 1):
                # 식당 정보 컨테이너
                with st.container():
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        st.markdown(f"**{i}. {restaurant.get('name', '이름 없음')}**")
                        st.markdown(
                            f"📍 주소: {restaurant.get('address', '주소 없음')}"
                        )

                        # 메뉴 정보가 있으면 표시
                        if "menus" in restaurant and restaurant["menus"]:
                            menu_text = ", ".join(
                                [
                                    menu.get("menu_name", "이름 없음")
                                    for menu in restaurant["menus"][:3]
                                ]
                            )
                            if len(restaurant["menus"]) > 3:
                                menu_text += " 외"
                            st.markdown(f"🍽️ 대표 메뉴: {menu_text}")

                    with col2:
                        # 지도에서 보기 버튼
                        if st.button(
                            "🗺️ 지도에서 보기", key=f"map_{restaurant.get('id', i)}"
                        ):
                            st.session_state.highlighted_restaurant = restaurant.get(
                                "id"
                            )
                            st.rerun()

                        # 유튜브 링크
                        if "video_url" in restaurant and restaurant["video_url"]:
                            st.markdown(f"[🎬 유튜브]({restaurant['video_url']})")

                st.divider()

# 오른쪽 컬럼: 채팅 인터페이스
with right_col:
    st.header("💬 맛집 추천 챗봇")

    # 채팅 컨테이너 생성 (고정 높이로 스크롤 가능)
    chat_container = st.container(height=500, border=True)

    # 채팅 컨테이너 내부에 메시지 표시
    with chat_container:
        # 채팅 기록 표시
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"], unsafe_allow_html=True)

    # 사용자 입력 (컨테이너 외부에 배치)
    prompt = st.chat_input(
        "맛집을 추천해드릴까요? (예: 서울에서 맛있는 한식 맛집 추천해줘)"
    )

    if prompt:
        # 사용자 메시지 추가
        st.session_state.messages.append({"role": "user", "content": prompt})

        # 사용자 메시지 표시 (컨테이너 내부에 추가)
        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)

        # 로딩 표시
        with chat_container:
            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                message_placeholder.markdown("🤔 맛집을 찾고 있어요...")

            # 에이전트 호출 및 응답 처리
            try:
                logger.info(f"에이전트 호출: {prompt}")

                # 에이전트 실행
                result = run_agent(prompt, st.session_state.agent_graph)
                logger.info(f"에이전트 응답 타입: {type(result)}")

                # 응답 처리
                if not isinstance(result, dict):
                    response = str(result)
                    logger.warning(f"예상치 못한 응답 타입: {type(result)}")
                else:
                    # 메시지에서 응답 추출
                    if "messages" in result and result["messages"]:
                        messages = result["messages"]
                        last_message = messages[-1]

                        if hasattr(last_message, "content"):
                            response = last_message.content
                        else:
                            response = str(last_message)

                        logger.info(f"마지막 메시지 내용: {response[:100]}...")
                    elif "response" in result:
                        response = result["response"]
                        logger.info(f"응답 내용: {response[:100]}...")
                    else:
                        response = "응답을 생성하는 데 문제가 발생했습니다."
                        logger.warning("응답 내용을 찾을 수 없음")

                # 식당 정보 추출 및 처리
                message_placeholder.markdown(response, unsafe_allow_html=True)

                # 식당 정보 분석
                restaurants = []

                # 응답 텍스트에서 식당 정보 추출 시도
                try:
                    # '다음과 같은 맛집을 찾았습니다' 패턴 체크
                    if "다음과 같은 맛집을 찾았습니다" in response:
                        # 응답 구조 분석해서 식당 정보 추출
                        lines = response.split("\n")
                        restaurant_data = []
                        current_restaurant = None

                        for line in lines:
                            line = line.strip()

                            # 식당 이름 패턴 (1. **식당이름**)
                            if (
                                line.startswith(("1.", "2.", "3.", "4.", "5."))
                                and "**" in line
                            ):
                                if current_restaurant:
                                    restaurant_data.append(current_restaurant)

                                name_start = line.find("**") + 2
                                name_end = line.find("**", name_start)
                                if name_end > name_start:
                                    restaurant_name = line[name_start:name_end]
                                    current_restaurant = {"name": restaurant_name}

                            # 주소 패턴
                            elif current_restaurant and "주소:" in line:
                                address = line.split("주소:", 1)[1].strip()
                                current_restaurant["address"] = address

                            # 영상 URL 패턴
                            elif current_restaurant and "영상:" in line:
                                video_url = line.split("영상:", 1)[1].strip()
                                current_restaurant["video_url"] = video_url

                        # 마지막 식당 추가
                        if current_restaurant:
                            restaurant_data.append(current_restaurant)

                        # 추출된 식당 정보가 있으면 restaurants에 추가
                        if restaurant_data:
                            restaurants = restaurant_data
                            logger.info(
                                f"응답에서 {len(restaurants)}개의 식당 정보를 추출했습니다."
                            )

                except Exception as e:
                    logger.error(f"식당 정보 추출 중 오류: {str(e)}")

                # 세션 상태에 식당 정보 저장
                if restaurants:
                    st.session_state.restaurants = restaurants

                    # 첫 번째 식당 하이라이트
                    if (
                        not st.session_state.get("highlighted_restaurant")
                        and restaurants
                    ):
                        st.session_state.highlighted_restaurant = restaurants[0].get(
                            "id"
                        )
                else:
                    logger.warning("추출된 식당 정보 없음")

                # 어시스턴트 메시지 추가
                st.session_state.messages.append(
                    {"role": "assistant", "content": response}
                )

                # 지도 업데이트를 위한 페이지 리로드 (식당 정보가 있을 때만)
                if restaurants:
                    st.rerun()

            except Exception as e:
                error_msg = f"맛집 검색 중 오류가 발생했습니다: {str(e)}"
                logger.error(f"에이전트 실행 오류: {str(e)}")
                message_placeholder.markdown(error_msg)
                st.session_state.messages.append(
                    {"role": "assistant", "content": error_msg}
                )

# URL 파라미터 처리
query_params = st.query_params
if "restaurant_id" in query_params:
    restaurant_id = query_params["restaurant_id"]
    # 세션 상태에 하이라이트할 식당 ID 저장
    st.session_state.highlighted_restaurant = restaurant_id
    # 페이지 리로드 없이 지도 업데이트
    st.rerun()


def process_agent_response(response):
    """에이전트 응답을 처리하는 함수"""
    try:
        # 응답에서 "Answer:" 부분 추출
        if isinstance(response, dict) and "response" in response:
            answer_text = response["response"]
        else:
            answer_text = str(response)

        if answer_text.startswith("Answer:"):
            answer_text = answer_text[7:].strip()

        # 식당 정보 추출
        restaurants = response.get("restaurants", [])

        # 식당 정보가 있으면 클릭 가능한 식당 이름으로 변환
        if restaurants:
            answer_text = add_clickable_restaurant_names(answer_text, restaurants)

        return answer_text
    except Exception as e:
        logger.error(f"응답 처리 중 오류 발생: {str(e)}")
        return str(response)


def display_restaurant_detail(restaurant_id):
    """식당 상세 정보를 표시하는 함수"""
    try:
        # DB에서 식당 정보 가져오기
        from utils.db_utils import MeoktenDB

        db = MeoktenDB()

        # 식당 정보 가져오기
        restaurant = db.get_restaurant_with_menus(restaurant_id)

        if not restaurant:
            st.error("식당 정보를 찾을 수 없습니다.")
            return

        # 식당 정보 표시
        st.subheader(f"🍽️ {restaurant['name']}")

        # 식당 정보와 메뉴 정보를 2개의 컬럼으로 표시
        col1, col2 = st.columns([1, 1])

        with col1:
            st.markdown(f"**주소:** {restaurant['address']}")
            st.markdown(f"**역:** {restaurant.get('station_name', '정보 없음')}")

            # 영상 링크가 있으면 표시
            if restaurant.get("video_url"):
                st.markdown(
                    f"**영상 링크:** [유튜브에서 보기]({restaurant['video_url']})"
                )

        with col2:
            # 메뉴 정보 표시
            if restaurant.get("menus"):
                st.markdown("### 메뉴")
                for menu in restaurant["menus"]:
                    st.markdown(f"**{menu['menu_name']}** ({menu['menu_type']})")
                    if menu.get("menu_review"):
                        st.markdown(f"_{menu['menu_review']}_")
                    st.markdown("---")
            else:
                st.markdown("메뉴 정보가 없습니다.")

    except Exception as e:
        logger.error(f"식당 상세 정보 표시 중 오류 발생: {str(e)}")
        st.error("식당 정보를 불러오는 중 오류가 발생했습니다.")
