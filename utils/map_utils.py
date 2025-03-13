# utils/map_utils.py
import folium
from folium.plugins import MarkerCluster, FeatureGroupSubGroup
from typing import List, Dict, Any
import random

# 지도 스타일 옵션
MAP_STYLES = {
    "기본": "OpenStreetMap",
    "밝은 테마": "CartoDB positron",
    "어두운 테마": "CartoDB dark_matter",
    "위성 이미지": "Stamen Terrain",
    "수채화 스타일": "Stamen Watercolor",
}


def create_simple_popup(restaurant: dict) -> str:
    """
    식당 정보를 바탕으로 간단한 팝업 내용을 생성합니다.

    Args:
        restaurant: 식당 정보 딕셔너리

    Returns:
        HTML 형식의 팝업 내용
    """
    name = restaurant.get("name", "이름 없음")
    address = restaurant.get("address", "주소 없음")
    station = restaurant.get("subway", "")

    # 메뉴 정보 (최대 2개까지만 표시)
    menu_html = ""
    if "menus" in restaurant and restaurant["menus"]:
        menus = restaurant["menus"][:2]  # 최대 2개까지만
        menu_names = [
            menu.get("menu_name", "") for menu in menus if menu.get("menu_name")
        ]
        if menu_names:
            menu_text = ", ".join(menu_names)
            if len(restaurant["menus"]) > 2:
                menu_text += " 외"
            menu_html = f"<p><strong>대표 메뉴:</strong> {menu_text}</p>"

    # 유튜브 링크
    video_html = ""
    if "video_url" in restaurant and restaurant["video_url"]:
        video_url = restaurant["video_url"]
        video_html = f'<p><a href="{video_url}" target="_blank" style="color: #FF0000;">🎬 유튜브 영상</a></p>'

    # 팝업 내용 생성 (간단한 형태)
    popup_content = f"""
    <div style="min-width: 150px; max-width: 200px; font-family: sans-serif;">
        <h4 style="margin: 5px 0; color: #333;">{name}</h4>
        <p style="margin: 3px 0; font-size: 12px;"><strong>주소:</strong> {address}</p>
        {f'<p style="margin: 3px 0; font-size: 12px;"><strong>역:</strong> {station}</p>' if station else ''}
        {menu_html.replace('<p>', '<p style="margin: 3px 0; font-size: 12px;">')}
        {video_html.replace('<p>', '<p style="margin: 3px 0; font-size: 12px;">')}
    </div>
    """

    return popup_content


def create_restaurant_map(
    restaurants: List[Dict[str, Any]],
    center=None,
    highlighted_id=None,
    use_clustering=True,
    zoom_start=14,
):
    """식당 정보를 지도에 표시, 특정 식당 하이라이트 가능"""
    # 중심 좌표 설정 (기본값: 서울)
    if center is None:
        center = [37.5665, 126.9780]

    # 지도 생성
    m = folium.Map(location=center, zoom_start=zoom_start, tiles="cartodbpositron")

    # 클러스터링 설정
    if use_clustering and len(restaurants) > 1:
        marker_cluster = MarkerCluster(name="식당 클러스터")
        marker_cluster.add_to(m)

        # 카테고리별 서브그룹 생성
        categories = {}
        for restaurant in restaurants:
            # 메뉴 정보에서 카테고리 추출
            category = "기타"
            if restaurant.get("menus"):
                menu_types = [
                    menu.get("menu_type", "") for menu in restaurant.get("menus", [])
                ]
                if menu_types and menu_types[0]:
                    category = menu_types[0]

            if category not in categories:
                categories[category] = FeatureGroupSubGroup(
                    marker_cluster, name=f"{category} 식당"
                )
                categories[category].add_to(m)

    # 서울 중심 좌표 (기본값)
    base_lat, base_lng = 37.5665, 126.9780

    # 식당 마커 추가
    for i, restaurant in enumerate(restaurants, 1):
        # 위도, 경도 확인
        try:
            # 좌표 데이터 처리 개선
            lat = restaurant.get("lat", None)
            lng = restaurant.get("lng", None)

            # 문자열인 경우 float로 변환
            if isinstance(lat, str) and lat not in ["정보 없음", "0", ""]:
                lat = float(lat)
            if isinstance(lng, str) and lng not in ["정보 없음", "0", ""]:
                lng = float(lng)

            # 유효한 좌표인지 확인
            if not lat or not lng or lat == 0 or lng == 0:
                print(
                    f"유효하지 않은 좌표: {restaurant['name']} - lat: {lat}, lng: {lng}"
                )
                # 기본 좌표에 오프셋 추가
                lat = base_lat + (i * 0.001)
                lng = base_lng + (i * 0.001)
                print(f"기본 좌표 할당: {restaurant['name']} - lat: {lat}, lng: {lng}")

            # 아이콘 선택
            icon_name = "cutlery"

            # 간단한 팝업 내용 생성
            popup_html = create_simple_popup(restaurant)

            # 하이라이트 여부 확인
            is_highlighted = str(restaurant.get("id", "")) == str(highlighted_id)

            # 마커 색상 및 아이콘 설정
            icon_color = (
                "red"
                if is_highlighted
                else random.choice(
                    [
                        "blue",
                        "green",
                        "purple",
                        "orange",
                        "darkblue",
                        "lightred",
                        "beige",
                        "darkgreen",
                        "darkpurple",
                        "cadetblue",
                    ]
                )
            )

            # 마커 생성
            marker = folium.Marker(
                location=[lat, lng],
                popup=folium.Popup(popup_html, max_width=200),
                tooltip=restaurant["name"],
                icon=folium.Icon(color=icon_color, icon=icon_name, prefix="fa"),
            )

            # 마커 추가 (클러스터링 사용 여부에 따라)
            if use_clustering and len(restaurants) > 1:
                if category in categories:
                    marker.add_to(categories[category])
                else:
                    marker.add_to(marker_cluster)
            else:
                marker.add_to(m)

            # 하이라이트된 마커에 추가 효과
            if is_highlighted:
                # 원형 마커 추가
                folium.CircleMarker(
                    location=[lat, lng],
                    radius=30,
                    color="#FF4B4B",
                    fill=True,
                    fill_color="#FF4B4B",
                    fill_opacity=0.2,
                    weight=3,
                ).add_to(m)

        except (ValueError, TypeError) as e:
            print(f"좌표 변환 오류: {restaurant.get('name', '이름 없음')} - {e}")
            # 오류 발생 시 기본 좌표에 오프셋 추가
            lat = base_lat + (i * 0.001)
            lng = base_lng + (i * 0.001)
            print(
                f"오류 발생으로 기본 좌표 할당: {restaurant.get('name', '이름 없음')} - lat: {lat}, lng: {lng}"
            )

            try:
                # 마커 생성 및 추가 시도
                marker = folium.Marker(
                    location=[lat, lng],
                    popup=folium.Popup(create_simple_popup(restaurant), max_width=200),
                    tooltip=restaurant.get("name", "이름 없음"),
                    icon=folium.Icon(color="gray", icon="question", prefix="fa"),
                )

                # 마커 추가
                if use_clustering and len(restaurants) > 1:
                    marker.add_to(marker_cluster)
                else:
                    marker.add_to(m)
            except Exception as e2:
                print(f"마커 생성 오류: {restaurant.get('name', '이름 없음')} - {e2}")
                continue

    # 레이어 컨트롤 추가 (클러스터링 사용 시)
    if use_clustering and len(restaurants) > 1 and categories:
        folium.LayerControl().add_to(m)

    return m
