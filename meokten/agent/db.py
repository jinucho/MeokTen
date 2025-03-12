import os

import requests
from agent.config import LLM, get_logger
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase

# 로깅 설정
logger = get_logger()


def get_db_connection():
    """데이터베이스 연결을 반환합니다."""
    db_url = "https://github.com/jinucho/Meokten/raw/refs/heads/main/meokten/meokten.db"

    response = requests.get(db_url)
    db_path = "meokten.db"
    with open(db_path, "wb") as file:
        file.write(response.content)

    llm = LLM()
    logger.info(f"데이터베이스 연결: {db_path}")
    db = SQLDatabase.from_uri(db_path)
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    return db, toolkit
