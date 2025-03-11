import ast
import logging
import os
from typing import Any, Dict, List

from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# 데이터베이스 파일 경로 찾기
def find_db_path():
    """데이터베이스 파일 경로 찾기"""
    current_dir = os.getcwd()

    # 가능한 데이터베이스 경로들
    possible_paths = [
        os.path.join(current_dir, "meokten.db"),
        os.path.join(os.path.dirname(current_dir), "meokten.db"),
        os.path.join(current_dir, "meokten", "meokten.db"),
    ]

    # 존재하는 첫 번째 경로 사용
    for path in possible_paths:
        if os.path.exists(path):
            logger.info(f"데이터베이스 파일 경로: {path}")
            return path

    # 기본 경로 반환
    default_path = os.path.join(current_dir, "meokten.db")
    logger.warning(f"데이터베이스 파일을 찾을 수 없어 기본 경로 사용: {default_path}")
    return default_path


# SQLDatabase 인스턴스 생성
db_path = find_db_path()
db = SQLDatabase.from_uri(f"sqlite:///{db_path}")
# Create SQLDatabaseToolkit
toolkit = SQLDatabaseToolkit(db=db, llm=ChatOpenAI(model="gpt-4o"))


@tool
def db_query_tool(query: str) -> str:
    """SQL 쿼리를 실행하고 결과를 반환합니다.
    올바른 SQLite 쿼리를 작성해야 합니다.
    사용 가능한 테이블: restaurants, menus
    """
    logger.info(f"SQL 쿼리 실행: {query}")

    try:
        # 쿼리 정제
        query = query.strip()
        if query.endswith(";"):
            query = query[:-1]

        # SQLDatabase를 사용하여 쿼리 실행
        result = db.run_no_throw(query)

        # 결과 로깅
        logger.info(f"쿼리 실행 결과 길이: {len(result) if result else 0}")

        # 결과가 없는 경우
        if not result or result.strip() == "":
            logger.warning("쿼리 실행 결과가 없습니다.")
            return "쿼리 실행 결과가 없습니다."

        return result
    except Exception as e:
        error_msg = f"쿼리 실행 중 오류 발생: {str(e)}"
        logger.error(error_msg)
        return error_msg


@tool
def get_table_info_tool(table_name: str) -> str:
    """테이블의 스키마 정보를 반환합니다.
    사용 가능한 테이블: restaurants, menus
    """
    logger.info(f"테이블 스키마 조회: {table_name}")

    try:
        # SQLDatabase를 사용하여 스키마 정보 조회
        schema_query = f"PRAGMA table_info({table_name});"
        schema_result = db.run(schema_query)

        if not schema_result or schema_result.strip() == "":
            return f"테이블 '{table_name}'의 스키마 정보를 찾을 수 없습니다."

        return f"{table_name} 테이블 스키마:\n{schema_result}"
    except Exception as e:
        error_msg = f"테이블 스키마 조회 중 오류 발생: {str(e)}"
        logger.error(error_msg)
        return error_msg


@tool
def list_tables_tool() -> str:
    """데이터베이스의 모든 테이블 목록을 반환합니다."""
    logger.info("테이블 목록 조회")

    try:
        # SQLDatabase를 사용하여 테이블 목록 조회
        tables_query = "SELECT name FROM sqlite_master WHERE type='table';"
        tables_result = db.run(tables_query)

        if not tables_result or tables_result.strip() == "":
            logger.warning("테이블 목록을 찾을 수 없습니다. 기본값 반환")
            return "['restaurants', 'menus']"

        logger.info(f"테이블 목록: {tables_result}")
        return tables_result
    except Exception as e:
        error_msg = f"테이블 목록 조회 중 오류 발생: {str(e)}"
        logger.error(error_msg)
        return "['restaurants', 'menus']"


@tool
def get_menus_by_restaurant_tool(restaurant_id: str) -> str:
    """식당 ID에 해당하는 메뉴 정보를 조회합니다."""
    logger.info(f"식당 ID로 메뉴 조회: {restaurant_id}")

    try:
        # 문자열 ID를 정수로 변환
        r_id = int(restaurant_id)

        # SQLDatabase를 사용하여 메뉴 정보 조회
        menus_query = f"SELECT * FROM menus WHERE restaurant_id = {r_id}"
        menus_result = db.run(menus_query)

        if not menus_result or menus_result.strip() == "":
            logger.warning(f"식당 ID {r_id}에 대한 메뉴 정보가 없습니다.")
            return "[]"

        logger.info(f"메뉴 조회 결과: {menus_result[:100]}...")
        return menus_result
    except Exception as e:
        error_msg = f"메뉴 조회 중 오류 발생: {str(e)}"
        logger.error(error_msg)
        return "[]"


# 문자열을 파이썬 객체로 변환하는 유틸리티 함수
def parse_str_to_obj(data_str: str):
    """문자열 형태의 데이터를 파이썬 객체로 변환"""
    try:
        # 결과가 표 형식인 경우 파싱
        if isinstance(data_str, str) and "|" in data_str and "-" in data_str:
            # 표 형식 데이터를 파싱하여 딕셔너리 리스트로 변환
            lines = data_str.strip().split("\n")
            if len(lines) < 3:  # 헤더, 구분선, 데이터 최소 3줄 필요
                return data_str

            # 헤더 추출
            headers = [h.strip() for h in lines[0].split("|") if h.strip()]

            # 데이터 행 추출 및 변환
            result = []
            for line in lines[2:]:  # 첫 번째 줄은 헤더, 두 번째 줄은 구분선
                if "|" not in line:
                    continue

                values = [v.strip() for v in line.split("|") if v.strip() != ""]
                if len(values) == len(headers):
                    row_dict = dict(zip(headers, values))
                    result.append(row_dict)

            return result
        else:
            # 일반 문자열은 ast.literal_eval로 변환 시도
            return ast.literal_eval(data_str)
    except (SyntaxError, ValueError) as e:
        logger.error(f"문자열 변환 중 오류 발생: {str(e)}")
        return data_str
