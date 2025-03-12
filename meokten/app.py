# app.py
import argparse
import ast
import json
import os
from typing import Any, Dict, List

import streamlit as st
from dotenv import load_dotenv
from streamlit_folium import folium_static

from agent.config import get_logger

# 커스텀 모듈 임포트
from agent.graph import AgentGraph
from utils.map_utils import create_restaurant_map


@st.cache_resource
def create_agent_graph():
    return AgentGraph()


# 로깅 설정 - app.log 파일에 로그 기록
logger = get_logger()

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


# 식당 JSON 파싱 함수
def parse_restaurant_info(response_text):
    """응답 텍스트에서 식당 정보를 추출합니다."""
    try:
        logger.info(f"파싱할 응답 텍스트: {response_text[:50]}...")

        # "Answer:" 텍스트 제거
        if response_text.startswith("Answer:"):
            response_text = response_text.replace("Answer: ", "").strip()

        # JSON 문자열을 파이썬 객체로 변환
        try:
            if "answer" in response_text:
                data = ast.literal_eval(response_text)
                # 식당 정보 추출
                Answer = data.get("answer", "")
                restaurants = []
                if isinstance(data, dict) and "infos" in data:
                    logger.info(f"응답에서 {len(data['infos'])}개의 식당 정보 발견")

                    # 서울 중심 좌표 (기본값)
                    base_lat, base_lng = 37.5665, 126.9780

                    for i, info in enumerate(data["infos"], 1):
                        # 좌표 정보 처리
                        try:
                            lat = info.get("lat", "0")
                            lng = info.get("lng", "0")

                            # 문자열인 경우 변환 처리
                            if isinstance(lat, str):
                                lat = float(lat) if lat and lat != "정보 없음" else 0
                            if isinstance(lng, str):
                                lng = float(lng) if lng and lng != "정보 없음" else 0

                            # 좌표가 없거나 0인 경우 기본 좌표에 오프셋 추가
                            if not lat or not lng or lat == 0 or lng == 0:
                                lat = base_lat + (i * 0.001)
                                lng = base_lng + (i * 0.001)
                                logger.info(
                                    f"식당 {i}에 기본 좌표 할당: lat={lat}, lng={lng}"
                                )
                        except (ValueError, TypeError) as e:
                            logger.warning(f"좌표 변환 오류, 기본값 사용: {str(e)}")
                            lat = base_lat + (i * 0.001)
                            lng = base_lng + (i * 0.001)

                        logger.info(
                            f"식당 {i}: {info.get('name', '이름 없음')} - 좌표: lat={lat}, lng={lng}"
                        )

                        Answer += f"\n\n{i}. {info.get('name', '이름 없음')}\n\n"
                        Answer += f"\t📍 주소: {info.get('address', '주소 없음')}\n\n"
                        Answer += f"\t🚇 지하철: {info.get('subway', '정보 없음')}\n\n"
                        Answer += f"\t🍽️ 메뉴: {info.get('menu', '정보 없음')}\n\n"
                        Answer += f"\t⭐ 리뷰: {info.get('review', '정보 없음')}\n\n"
                        restaurant = {
                            "id": i,
                            "name": info.get("name", "이름 없음"),
                            "address": info.get("address", "주소 없음"),
                            "subway": info.get("subway", "정보 없음"),
                            "menu": info.get("menu", "정보 없음"),
                            "review": info.get("review", "정보 없음"),
                            "lat": lat,
                            "lng": lng,
                        }
                        restaurants.append(restaurant)
                elif isinstance(data, list):
                    # 직접 식당 목록이 전달된 경우 (예: [{...}, {...}])
                    logger.info(f"응답에서 {len(data)}개의 식당 정보 발견")

                    # 서울 중심 좌표 (기본값)
                    base_lat, base_lng = 37.5665, 126.9780

                    for i, info in enumerate(data, 1):
                        # 좌표 정보 처리
                        try:
                            lat = info.get("lat", "0")
                            lng = info.get("lng", "0")

                            # 문자열인 경우 변환 처리
                            if isinstance(lat, str):
                                lat = float(lat) if lat and lat != "정보 없음" else 0
                            if isinstance(lng, str):
                                lng = float(lng) if lng and lng != "정보 없음" else 0

                            # 좌표가 없거나 0인 경우 기본 좌표에 오프셋 추가
                            if not lat or not lng or lat == 0 or lng == 0:
                                lat = base_lat + (i * 0.001)
                                lng = base_lng + (i * 0.001)
                                logger.info(
                                    f"식당 {i}에 기본 좌표 할당: lat={lat}, lng={lng}"
                                )
                        except (ValueError, TypeError) as e:
                            logger.warning(f"좌표 변환 오류, 기본값 사용: {str(e)}")
                            lat = base_lat + (i * 0.001)
                            lng = base_lng + (i * 0.001)

                        logger.info(
                            f"식당 {i}: {info.get('name', '이름 없음')} - 좌표: lat={lat}, lng={lng}"
                        )

                        Answer += f"\n\n{i}. {info.get('name', '이름 없음')}\n\n"
                        Answer += f"\t📍 주소: {info.get('address', '주소 없음')}\n\n"
                        Answer += f"\t🚇 지하철: {info.get('subway', '정보 없음')}\n\n"
                        Answer += f"\t🍽️ 메뉴: {info.get('menu', '정보 없음')}\n\n"
                        Answer += f"\t⭐ 리뷰: {info.get('review', '정보 없음')}\n"
                        restaurant = {
                            "id": i,
                            "name": info.get("name", "이름 없음"),
                            "address": info.get("address", "주소 없음"),
                            "subway": info.get("subway", "정보 없음"),
                            "menu": info.get("menu", "정보 없음"),
                            "review": info.get("review", "정보 없음"),
                            "lat": lat,
                            "lng": lng,
                        }
                        restaurants.append(restaurant)

                # 추출된 식당 정보 요약 로깅
                logger.info(f"총 {len(restaurants)}개 식당 정보 추출 완료")
                for i, r in enumerate(restaurants, 1):
                    logger.info(
                        f"추출된 식당 {i}: {r.get('name')} - 좌표: lat={r.get('lat')}, lng={r.get('lng')}"
                    )

                return Answer, restaurants
            else:
                return response_text, []

        except (json.JSONDecodeError, SyntaxError, ValueError) as e:
            logger.error(f"JSON 파싱 오류: {str(e)}")
            logger.debug(f"파싱 실패한 문자열: {response_text}")
            return response_text, []

    except Exception as e:
        logger.error(f"식당 정보 파싱 오류: {str(e)}")
        return response_text, []


# 식당 하이라이트 함수
def highlight_restaurant(restaurant_id):
    """식당을 하이라이트하는 함수"""
    logger.info(f"식당 하이라이트 요청: ID={restaurant_id}")
    st.session_state.highlighted_restaurant = int(restaurant_id)
    # URL 파라미터 설정을 위한 쿼리 파라미터 업데이트
    st.query_params["restaurant_id"] = restaurant_id


# 좌우 컬럼 생성
left_col, right_col = st.columns([1, 1])

# 왼쪽 컬럼: 지도 표시
with left_col:
    st.header("🗺️ 맛집 지도")

    # 지도 표시 (식당 정보가 있는 경우)
    if "restaurants" in st.session_state and st.session_state.restaurants:
        # 유효한 좌표가 있는 식당 필터링
        valid_restaurants = []
        for restaurant in st.session_state.restaurants:
            try:
                lat = restaurant.get("lat")
                lng = restaurant.get("lng")

                # 숫자형으로 변환 확인
                if isinstance(lat, (str, float, int)) and lat not in [
                    "정보 없음",
                    "0",
                    "",
                    0,
                ]:
                    if isinstance(lat, str):
                        lat = float(lat)
                if isinstance(lng, (str, float, int)) and lng not in [
                    "정보 없음",
                    "0",
                    "",
                    0,
                ]:
                    if isinstance(lng, str):
                        lng = float(lng)

                # 유효한 좌표인 경우만 추가 (엄격하게 검사)
                if lat and lng and lat != 0 and lng != 0:
                    # 좌표 정보 업데이트
                    restaurant_with_coords = restaurant.copy()
                    restaurant_with_coords["lat"] = lat
                    restaurant_with_coords["lng"] = lng
                    valid_restaurants.append(restaurant_with_coords)
                    logger.info(
                        f"유효한 좌표: {restaurant.get('name')} - lat={lat}, lng={lng}"
                    )
                else:
                    logger.warning(
                        f"유효하지 않은 좌표: {restaurant.get('name', '이름 없음')} - lat={lat}, lng={lng}"
                    )
                    # 기본 좌표 할당
                    base_lat, base_lng = 37.5665, 126.9780
                    idx = restaurant.get("id", 1)
                    lat = base_lat + (idx * 0.001)
                    lng = base_lng + (idx * 0.001)
                    restaurant_with_coords = restaurant.copy()
                    restaurant_with_coords["lat"] = lat
                    restaurant_with_coords["lng"] = lng
                    valid_restaurants.append(restaurant_with_coords)
                    logger.info(
                        f"기본 좌표 할당: {restaurant.get('name')} - lat={lat}, lng={lng}"
                    )
            except (ValueError, TypeError) as e:
                logger.warning(
                    f"좌표 변환 오류: {str(e)}, 식당: {restaurant.get('name', '이름 없음')}"
                )
                # 오류 발생 시 기본 좌표 할당
                base_lat, base_lng = 37.5665, 126.9780
                idx = restaurant.get("id", 1)
                restaurant_with_coords = restaurant.copy()
                restaurant_with_coords["lat"] = base_lat + (idx * 0.001)
                restaurant_with_coords["lng"] = base_lng + (idx * 0.001)
                valid_restaurants.append(restaurant_with_coords)
                logger.info(
                    f"오류 후 기본 좌표 할당: {restaurant.get('name')} - lat={base_lat + (idx * 0.001)}, lng={base_lng + (idx * 0.001)}"
                )

        # 식당이 있는 경우 항상 지도 생성 (유효한 좌표가 없어도 기본 좌표로 표시)
        if st.session_state.restaurants:
            # 하이라이트된 식당 ID 가져오기
            highlighted_id = st.session_state.get("highlighted_restaurant")
            logger.info(f"하이라이트된 식당 ID: {highlighted_id}")

            # 중심 좌표 계산
            center = None
            if highlighted_id:
                for r in valid_restaurants:
                    if r.get("id") == highlighted_id:
                        try:
                            center = [
                                float(r.get("lat")),
                                float(r.get("lng")),
                            ]
                            logger.info(f"하이라이트된 식당 중심 좌표: {center}")
                            break
                        except (ValueError, TypeError):
                            pass

            if not center and valid_restaurants:
                try:
                    center_lat = float(valid_restaurants[0].get("lat", 37.5665))
                    center_lng = float(valid_restaurants[0].get("lng", 126.9780))
                    center = [center_lat, center_lng]
                    logger.info(f"첫 번째 식당 중심 좌표: {center}")
                except (ValueError, TypeError):
                    center = [37.5665, 126.9780]  # 기본값: 서울
                    logger.info(f"기본 중심 좌표 사용: {center}")
            else:
                # center가 설정되지 않았을 경우 기본값 설정
                if not center:
                    center = [37.5665, 126.9780]  # 기본값: 서울
                    logger.info(f"기본 중심 좌표 사용: {center}")

            # 지도 생성 및 표시
            st.info(f"총 {len(valid_restaurants)}개의 식당을 지도에 표시합니다.")
            logger.info(f"지도에 표시할 식당 수: {len(valid_restaurants)}")
            m = create_restaurant_map(
                valid_restaurants,
                center=center,
                highlighted_id=highlighted_id,
                use_clustering=True,
            )
            folium_static(m)
            st.caption(f"총 {len(valid_restaurants)}개의 식당이 지도에 표시되었습니다.")
        else:
            st.warning("표시할 식당 정보가 없습니다.")
            logger.warning("유효한 식당 정보가 없어 빈 지도 표시")
            # 빈 지도 표시 (서울 중심)
            empty_map = create_restaurant_map([], center=[37.5665, 126.9780])
            folium_static(empty_map)
    else:
        st.info("검색 결과가 지도에 표시됩니다.")
        logger.info("식당 정보 없음, 빈 지도 표시")
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
                        st.markdown(
                            f"🚇 지하철: {restaurant.get('subway', '정보 없음')}"
                        )
                        st.markdown(f"⭐ 리뷰: {restaurant.get('review', '정보 없음')}")

                    with col2:
                        # 지도에서 보기 버튼
                        if st.button("🗺️ 지도에서 보기", key=f"map_{i}"):
                            highlight_restaurant(i)
                            st.rerun()

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
                result = st.session_state.agent_graph.run_agent(prompt)
                logger.info(f"에이전트 실행 결과: {result}")
                logger.info(f"에이전트 응답 타입: {type(result)}")

                # 응답 처리
                if not isinstance(result, dict):
                    response = str(result)
                    logger.warning(f"예상치 못한 응답 타입: {type(result)}")
                else:
                    # 응답에서 메시지 추출
                    if "response" in result:
                        response = result["response"]
                        logger.info(f"응답 내용: {response[:100]}...")
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
                        else:
                            response = "응답을 생성하는 데 문제가 발생했습니다."
                            logger.warning("응답 내용을 찾을 수 없음")

                # 식당 정보 추출 및 처리

                # 식당 정보 분석
                Answer, restaurants = parse_restaurant_info(response)

                # message_placeholder.markdown(Answer, unsafe_allow_html=True)
                message_placeholder.markdown(Answer)
                # 식당 정보가 있으면 세션 상태에 저장
                if restaurants:
                    logger.info(f"{len(restaurants)}개의 식당 정보 추출됨")
                    st.session_state.restaurants = restaurants

                    # 첫 번째 식당 하이라이트
                    if (
                        not st.session_state.get("highlighted_restaurant")
                        and restaurants
                    ):
                        st.session_state.highlighted_restaurant = 1
                else:
                    logger.warning("추출된 식당 정보 없음")

                # 어시스턴트 메시지 추가
                st.session_state.messages.append(
                    {"role": "assistant", "content": Answer}
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
    try:
        # 문자열을 정수로 변환
        restaurant_id = int(restaurant_id)
        # 세션 상태에 하이라이트할 식당 ID 저장
        st.session_state.highlighted_restaurant = restaurant_id
        logger.info(f"URL 파라미터에서 식당 ID 로드: {restaurant_id}")
    except (ValueError, TypeError) as e:
        logger.error(f"식당 ID 파라미터 처리 오류: {str(e)}")
