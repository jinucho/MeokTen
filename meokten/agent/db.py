import os

from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase

from agent.config import LLM, get_logger

# 로깅 설정
logger = get_logger()


def get_db_path():
    """데이터베이스 파일 경로를 반환합니다."""
    current_dir = os.getcwd()

    # 1. 현재 디렉토리 확인
    db_path = os.path.join(current_dir, "meokten.db")
    if os.path.exists(db_path):
        logger.info(f"데이터베이스 파일 경로: {db_path}")
        return db_path

    # 2. 상위 디렉토리 확인
    db_path = os.path.join(os.path.dirname(current_dir), "meokten.db")
    if os.path.exists(db_path):
        logger.info(f"상위 디렉토리에 데이터베이스 파일 존재: {db_path}")
        return db_path

    # 3. 절대 경로 사용
    db_path = os.path.join("/Users/jinucho/my_ws/Meokten/meokten", "meokten.db")
    if os.path.exists(db_path):
        logger.info(f"절대 경로에 데이터베이스 파일 존재: {db_path}")
        return db_path

    logger.warning("데이터베이스 파일을 찾을 수 없습니다.")
    return "sqlite:///meokten.db"  # 기본값


def get_db_connection():
    """데이터베이스 연결을 반환합니다."""
    db_path = get_db_path()

    # SQLite URI 형식으로 변환
    if not db_path.startswith("sqlite:///"):
        db_uri = f"sqlite:///{db_path}"
    else:
        db_uri = db_path
    llm = LLM()
    logger.info(f"데이터베이스 연결: {db_uri}")
    db = SQLDatabase.from_uri(db_uri)
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    return db, toolkit
