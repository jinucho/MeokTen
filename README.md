# MeokTen

## 프로젝트 소개
성시경의 유튜브 채널 '먹을텐데' 플레이리스트를 기반으로 한 맛집 추천 서비스입니다. 유튜브 영상에서 소개된 맛집 정보를 자동으로 수집하고 분석하여 사용자에게 맞춤형 맛집 추천을 제공합니다.

## 주요 기능
- **맛집 데이터 자동 수집**: YouTube API와 yt_dlp를 활용하여 '먹을텐데' 플레이리스트의 영상 정보 및 자막을 수집
- **메뉴 정보 추출**: LLM(GPT-4o)을 활용하여 영상 자막에서 메뉴 정보, 리뷰 내용을 자동으로 추출
- **지능형 검색**: SQL Agent를 기반으로 지역, 메뉴 타입 등 다양한 조건으로 맛집 검색 가능
- **지도 시각화**: 카카오 지도 API를 활용하여 검색된 맛집을 지도상에 표시
- **맞춤형 추천**: 사용자 질의에 따라 LLM이 최적의 맛집을 추천하고 상세 정보 제공

## 기술 스택
- **백엔드**: Python, SQLite
- **데이터 수집**: yt_dlp, YouTube Transcript API
- **AI/ML**: LangChain, OpenAI GPT-4o
- **지리정보**: Kakao Maps API
- **로깅**: Python logging 모듈

## 데이터베이스 구조
- **restaurants**: 식당 기본 정보 (이름, 주소, 위도/경도, 영상 ID, URL)
- **menus**: 각 식당의 메뉴 정보 (메뉴 타입, 메뉴명, 리뷰)

## 설치 및 실행 방법
1. 저장소 클론
   ```bash
   git clone https://github.com/yourusername/meokten.git
   cd meokten
   ```

2. 필요 패키지 설치
   ```bash
   pip install -r requirements.txt
   ```

3. 환경 변수 설정
   ```bash
   # .env 파일 생성
   OPENAI_API_KEY=your_openai_api_key
   KAKAO_API_KEY=your_kakao_api_key
   YOUTUBE_COOKIES=your_base64_encoded_cookies  # 선택사항
   ```

4. 데이터 수집 실행
   ```bash
   python collecting_data.py
   ```

5. 데이터베이스 구축
   ```bash
   python save_db.py
   ```

6. 서비스 실행
   ```bash
   # 실행 방법은 프로젝트에 맞게 수정
   ```

## 프로젝트 구조
```
meokten/
├── collecting_data.py  # 유튜브 데이터 수집
├── save_db.py          # 데이터베이스 저장
├── meokten_playlist/   # 수집된 텍스트 데이터
├── logs/               # 로그 파일
├── meokten.db          # SQLite 데이터베이스
└── README.md
```

## 데이터 수집 과정
1. YouTube 플레이리스트에서 영상 정보 추출
2. 각 영상의 설명에서 식당명과 주소 추출
3. 카카오 API를 통해 주소의 위도/경도 정보 획득
4. YouTube 자막 API를 통해 영상 자막 추출
5. GPT-4o를 활용하여 자막에서 메뉴 정보 및 리뷰 추출
6. 추출된 정보를 구조화하여 데이터베이스에 저장

## 향후 계획
- Tavily Search를 이용하여 일반 검색 결과도 제공

---

*이 프로젝트는 성시경의 '먹을텐데' 콘텐츠를 기반으로 하며, 모든 저작권은 원 저작자에게 있습니다.*
