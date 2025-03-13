from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableLambda, RunnableWithFallbacks
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode

from agent.db import get_db_connection
from agent.config import get_logger

# 로깅 설정
logger = get_logger()

# 도구 가져오기
db, toolkit = get_db_connection()
tools = toolkit.get_tools()

# 테이블 목록 도구
list_tables_tool = next(tool for tool in tools if tool.name == "sql_db_list_tables")

# 스키마 가져오기 도구
get_schema_tool = next(tool for tool in tools if tool.name == "sql_db_schema")


# 쿼리 실행 도구
@tool
def db_query_tool(query: str) -> str:
    """
    Run SQL queries against a database and return results
    Returns an error message if the query is incorrect
    If an error is returned, rewrite the query, check, and retry
    """
    # 쿼리 실행
    try:
        logger.info(f"실행할 쿼리: {query}")
        result = db.run_no_throw(query)

        # 에러: 결과가 없는 경우
        if not result:
            logger.warning("쿼리 실패")
            return "Error: Query failed. Please rewrite your query and try again."

        # 성공: 쿼리 실행 결과 반환
        logger.info("쿼리 성공")
        return result
    except Exception as e:
        logger.error(f"쿼리 실행 중 오류: {str(e)}")
        return f"Error: {str(e)}"


# 에러 처리 함수
def handle_tool_error(state) -> dict:
    """도구 에러 처리 함수"""
    # 에러 정보 확인
    error = state.get("error")
    # 도구 정보 확인
    tool_calls = state["messages"][-1].tool_calls
    # ToolMessage로 감싸서 반환
    return {
        "messages": [
            ToolMessage(
                content=f"Here is the error: {repr(error)}\n\nPlease fix your mistakes.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
    }


# 에러 처리 기능이 포함된 ToolNode 생성 함수
def create_tool_node_with_fallback(tools: list) -> RunnableWithFallbacks[Any, dict]:
    """
    Create a ToolNode with a fallback to handle errors and surface them to the agent.
    """
    # Add fallback behavior for error handling to the ToolNode
    return ToolNode(tools).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )
