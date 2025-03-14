# app.py
import streamlit as st
from dotenv import load_dotenv
from streamlit_folium import st_folium

from agent.config import get_logger

# from agent.db import get_db_connection

# 커스텀 모듈 임포트
from agent.graph import AgentGraph
from utils.map_utils import create_restaurant_map

st.set_page_config(page_title="먹텐 - 맛집 추천 AI", page_icon="🍽️", layout="wide")


@st.cache_resource
def create_agent_graph():
    return AgentGraph()


# @st.cache_resource
# def get_db():
#     return get_db_connection()


# 로깅 설정 - app.log 파일에 로그 기록
logger = get_logger()

# # db 연결
# db, _ = get_db()
# db._execute("SELECT count(*) FROM restaurants")[0]["count(*)"]

# 지도 크기 설정 (고정 값으로 유지)
MAP_WIDTH = 800
MAP_HEIGHT = 700

# 환경 변수 로드
load_dotenv()

# 페이지 설정

# 그래프를 세션 상태에 저장 (최초 접속 시 1회만 생성)
if "agent_graph" not in st.session_state:
    logger.info("에이전트 그래프 초기화")
    st.session_state.agent_graph = create_agent_graph()
    logger.info("에이전트 그래프 초기화 완료")

# 자바스크립트 코드 추가 (이벤트 리스너, 자동 스크롤, 지도 크기 유지)
st.markdown(
    f"""
    <style>
    /* 지도 컨테이너 크기 유지를 위한 CSS */
    [data-testid="stContainer"] {{
        min-height: {MAP_HEIGHT}px !important;
        height: {MAP_HEIGHT}px !important;
    }}
    /* 특정 지도 컨테이너에 적용 (좀 더 구체적인 선택자) */
    [data-testid="column"]:first-child [data-testid="stContainer"] {{
        min-height: {MAP_HEIGHT}px !important;
        height: {MAP_HEIGHT}px !important;
    }}
    .folium-map {{
        width: 100%;
        height: {MAP_HEIGHT}px !important;
        min-height: {MAP_HEIGHT}px !important;
        z-index: 1;
    }}
    iframe {{
        height: {MAP_HEIGHT}px !important;
        min-height: {MAP_HEIGHT}px !important;
        width: 100% !important;
    }}
    .stApp [data-testid="column"] {{
        overflow: visible !important;
    }}
    /* 왼쪽 컬럼 지도 영역 스타일 */
    [data-testid="column"]:first-child {{
        min-height: {MAP_HEIGHT + 100}px !important;
        height: auto !important;
    }}
    
    /* 지도가 표시되는 영역이 충분한 공간을 가지도록 함 */
    [data-testid="column"]:first-child [data-testid="block-container"] {{
        height: auto !important;
        min-height: {MAP_HEIGHT}px !important;
        padding-bottom: 50px !important;
    }}
    </style>
    <script>
    // 메시지 이벤트 리스너 설정
    window.addEventListener('message', function(e) {{
        if (e.data && e.data.type === 'highlight_restaurant') {{
            // URL 파라미터 설정하여 페이지 리로드
            const url = new URL(window.location.href);
            url.searchParams.set('restaurant_id', e.data.id);
            window.location.href = url.toString();
        }}
    }});
    
    // 자동 스크롤 함수
    function scrollChatToBottom() {{
        var chatContainer = document.querySelector('[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlock"]');
        if (chatContainer) {{
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }}
    }}
    
    // 지도 크기 유지 함수
    function maintainMapSize() {{
        // 지도 iframe 찾기
        const mapIframes = document.querySelectorAll('.folium-map iframe');
        mapIframes.forEach(iframe => {{
            iframe.style.height = '{MAP_HEIGHT}px';
            iframe.style.minHeight = '{MAP_HEIGHT}px';
            iframe.style.width = '100%';
        }});
        
        // 지도 컨테이너 찾기 (좀 더 정확한 선택자 사용)
        const leftColumn = document.querySelector('[data-testid="column"]:first-child');
        if (leftColumn) {{
            const mapContainers = leftColumn.querySelectorAll('[data-testid="stContainer"]');
            mapContainers.forEach(container => {{
                container.style.minHeight = '{MAP_HEIGHT}px';
                container.style.height = '{MAP_HEIGHT}px';
            }});
            
            // 왼쪽 컬럼 자체의 크기도 조정
            leftColumn.style.minHeight = '{MAP_HEIGHT + 100}px';
        }}
        
        // 전체 지도 영역 강제 리사이징
        const mapElements = document.querySelectorAll('.folium-map');
        mapElements.forEach(map => {{
            map.style.height = '{MAP_HEIGHT}px';
            map.style.minHeight = '{MAP_HEIGHT}px';
        }});
    }}
    
    // 페이지 로드 후 실행
    window.addEventListener('load', function() {{
        scrollChatToBottom();
        maintainMapSize();
        
        // MutationObserver를 사용하여 DOM 변경 감지 및 지도 크기 유지
        const observer = new MutationObserver(function(mutations) {{
            maintainMapSize();
        }});
        
        // body의 모든 하위 요소 변경 감시
        observer.observe(document.body, {{ 
            childList: true, 
            subtree: true 
        }});
    }});
    
    // 1초마다 스크롤 (새 메시지가 추가될 때)
    setInterval(scrollChatToBottom, 1000);
    
    // 0.5초마다 지도 크기 확인 및 조정
    setInterval(maintainMapSize, 500);
    </script>
    """,
    unsafe_allow_html=True,
)

# 제목 및 소개
st.title("🍽️ 먹텐 - 맛집 추천 AI")
st.subheader("성시경의 '먹을텐데' 맛집 추천 서비스")
st.markdown(
    """
    성시경이 유튜브 채널 '먹~을~텐데'에서 소개한 맛집을 추천해드립니다.
    지역, 음식 종류 등을 입력하시면 맞춤형 맛집을 추천해드립니다.
    """
)
# st.write(f"총 {data_count}개의 맛집 데이터가 있습니다.")

# 사이드바
with st.sidebar:
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
    st.markdown("데이터 출처: 성시경의 유튜브 채널")

# 메인 컨텐츠
# 채팅 기록 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.restaurants = []
    st.session_state.highlighted_restaurant = None  # 하이라이트할 식당 ID


# 식당 JSON 파싱 함수
def parse_restaurant_info(data):
    try:
        if "answer" in data:
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
                    Answer += (
                        f"\t🎬 유튜브 영상: {info.get('video_url', '정보 없음')}\n\n"
                    )
                    restaurant = {
                        "id": i,
                        "name": info.get("name", "이름 없음"),
                        "address": info.get("address", "주소 없음"),
                        "subway": info.get("subway", "정보 없음"),
                        "menu": info.get("menu", "정보 없음"),
                        "review": info.get("review", "정보 없음"),
                        "video_url": info.get("video_url", "정보 없음"),
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
            return data, []

    except Exception as e:
        logger.error(f"JSON 파싱 오류: {str(e)}")
        logger.debug(f"파싱 실패한 문자열: {data}")
        return data, []


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
    st.header("🗺️ 먹텐 지도")

    # 지도를 담을 고정 크기 컨테이너 생성
    map_container = st.container(height=MAP_HEIGHT, border=False)

    with map_container:
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
                # 반환 객체를 빈 리스트로 설정하여 지도 크기 유지
                st_folium(
                    m,
                    width="100%",
                    height=MAP_HEIGHT,
                    returned_objects=[],
                    key="folium_map_main",
                )
                st.caption(
                    f"총 {len(valid_restaurants)}개의 식당이 지도에 표시되었습니다."
                )
            else:
                st.warning("표시할 식당 정보가 없습니다.")
                logger.warning("유효한 식당 정보가 없어 빈 지도 표시")
                # 빈 지도 표시 (서울 중심)
                empty_map = create_restaurant_map([], center=[37.5665, 126.9780])
                # 반환 객체를 빈 리스트로 설정하여 지도 크기 유지
                st_folium(
                    empty_map,
                    width="100%",
                    height=MAP_HEIGHT,
                    returned_objects=[],
                    key="folium_map_empty",
                )
        else:
            st.text("검색 결과가 지도에 표시됩니다.")
            logger.info("식당 정보 없음, 빈 지도 표시")
            # 빈 지도 표시 (서울 중심)
            empty_map = create_restaurant_map([], center=[37.5665, 126.9780])
            # 반환 객체를 빈 리스트로 설정하여 지도 크기 유지
            st_folium(
                empty_map,
                width="100%",
                height=MAP_HEIGHT,
                returned_objects=[],
                key="folium_map_initial",
            )

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
                        st.markdown(f"🍽️ 메뉴: {restaurant.get('menu', '정보 없음')}")
                        st.markdown(f"⭐ 리뷰: {restaurant.get('review', '정보 없음')}")
                        st.markdown(
                            f"🎬 유튜브 영상: {restaurant.get('video_url', '정보 없음')}"
                        )

                    with col2:
                        # 지도에서 보기 버튼
                        if st.button("🗺️ 지도에서 보기", key=f"map_{i}"):
                            highlight_restaurant(i)
                            st.rerun()

                st.divider()

# 오른쪽 컬럼: 채팅 인터페이스
with right_col:
    st.header("💬 먹텐 챗봇")

    # 채팅 컨테이너 생성 (고정 높이로 스크롤 가능)
    chat_container = st.container(height=500, border=True)

    # 채팅 컨테이너 내부에 메시지 표시
    with chat_container:
        # 채팅 기록 표시
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"], unsafe_allow_html=True)

        # 처리 상태 확인
        if "processing" in st.session_state and st.session_state.processing:
            with st.chat_message("assistant"):
                st.write("🤔먹을 텐데~\n 식당을 찾고있어요.")

    # 사용자 입력 (컨테이너 외부에 배치)
    prompt = st.chat_input(
        "맛집을 추천해드릴까요? (예: 서울에서 맛있는 한식 맛집 추천해줘)"
    )

    if prompt:
        # 처리 중인지 확인
        if "processing" not in st.session_state:
            st.session_state.processing = False

        # 이미 처리 중이면 무시
        if st.session_state.processing:
            st.stop()

        # 사용자 메시지 추가 및 즉시 표시
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.processing = True
        st.rerun()  # 사용자 메시지 표시를 위해 즉시 리로드

    # 응답 생성 로직 (처리 중일 때만 실행)
    if "processing" in st.session_state and st.session_state.processing:
        try:
            logger.info(f"에이전트 호출: {st.session_state.messages[-1]['content']}")

            # 에이전트 실행
            result = st.session_state.agent_graph.run_agent(
                st.session_state.messages[-1]["content"]
            )
            logger.info(f"에이전트 실행 결과: {result}")
            logger.info(f"에이전트 응답 타입: {type(result)}")

            # 응답 처리
            if isinstance(result, dict):
                # 딕셔너리 형식의 응답 처리
                answer, restaurants = parse_restaurant_info(result)

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
                    logger.info("식당 정보가 없습니다")
            else:
                answer = "식당 정보가 없거나 오류가 발생했습니다."

            # 어시스턴트 메시지 추가
            st.session_state.messages.append({"role": "assistant", "content": answer})

            # 처리 완료 표시
            st.session_state.processing = False

            # 지도 업데이트를 위한 페이지 리로드
            st.rerun()

        except Exception as e:
            error_msg = f"맛집 검색 중 오류가 발생했습니다: {str(e)}"
            logger.error(f"에이전트 실행 오류: {str(e)}")

            # 어시스턴트 메시지 추가
            st.session_state.messages.append(
                {"role": "assistant", "content": error_msg}
            )

            # 처리 완료 표시
            st.session_state.processing = False

            # 에러 표시를 위한 페이지 리로드
            st.rerun()

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
