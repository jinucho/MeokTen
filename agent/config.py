import logging
import os
from pathlib import Path
from typing import Annotated, List

from dotenv import load_dotenv
from langchain_core.messages import AnyMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

load_dotenv()

# logs 디렉토리가 없으면 생성
os.makedirs("logs", exist_ok=True)


# 로깅 설정을 구성하는 함수
def get_logger():
    # 기본 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 루트 로거 핸들러 초기화
    root_logger = logging.getLogger()
    # 기존 핸들러 제거
    if root_logger.handlers:
        for handler in root_logger.handlers:
            root_logger.removeHandler(handler)

    # 파일 핸들러 생성 (기본 로그)
    file_name = Path(__file__).stem
    file_handler = logging.FileHandler(f"logs/app.log")
    file_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # 콘솔 핸들러 추가
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(file_formatter)
    root_logger.addHandler(console_handler)

    return root_logger


# 에이전트 상태 정의
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


# 식당 정보 모델
class Info(BaseModel):
    name: str = Field(..., description="식당 이름")
    address: str = Field(..., description="식당 주소")
    subway: str = Field(..., description="식당 지하철역")
    lat: str = Field(..., description="식당 위도")
    lng: str = Field(..., description="식당 경도")
    menu: str = Field(..., description="식당 메뉴")
    review: str = Field(..., description="식당 후기")


# 최종 응답 모델
class Answers(BaseModel):
    answer: str = Field(..., description="답변 내용")
    infos: List[Info] = Field(..., description="식당 정보")


# LLM 설정
def LLM():
    return ChatOpenAI(model="gpt-4o")
