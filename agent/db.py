import os

import requests
from agent.config import LLM, get_logger
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase

# 로깅 설정
logger = get_logger()


def get_db_connection():
    """데이터베이스 연결을 반환합니다."""
    # streamlit cloud 환경에서 사용할 목적으로 url 사용
    db_url = "https://github.com/jinucho/Meokten/raw/refs/heads/main/meokten.db"

    response = requests.get(db_url)
    db_path = "meokten.db"
    with open(db_path, "wb") as file:
        file.write(response.content)

    llm = LLM()
    db = SQLDatabase.from_uri(f"sqlite:///{db_path}")
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    return db, toolkit
