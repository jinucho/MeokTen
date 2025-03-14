import uuid
from typing import Literal

from agent.config import LLM, State, get_logger
from agent.prompt_chains import answer_gen, query_check, query_gen

# 내부 모듈 import
from agent.tools import (
    create_tool_node_with_fallback,
    db_query_tool,
    get_schema_tool,
    list_tables_tool,
)
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

# 로깅 설정 - graph.log 파일에 로그를 남김
logger = get_logger()


# 그래프 생성 함수
class AgentGraph:
    def __init__(self):
        """SQL 에이전트 그래프를 생성합니다."""
        # 새 그래프 생성
        workflow = StateGraph(State)
        # 노드 추가
        workflow.add_node("first_tool_call", self.first_tool_call)
        workflow.add_node(
            "list_tables_tool", create_tool_node_with_fallback([list_tables_tool])
        )

        # 관련 테이블 선택을 위한 모델 노드 추가
        self.model_get_schema = LLM().bind_tools([get_schema_tool])
        workflow.add_node(
            "model_get_schema",
            lambda state: {
                "messages": [self.model_get_schema.invoke(state["messages"])],
            },
        )

        workflow.add_node(
            "get_schema_tool", create_tool_node_with_fallback([get_schema_tool])
        )
        workflow.add_node("query_gen", self.query_gen_node)
        workflow.add_node("correct_query", self.model_check_query)
        workflow.add_node(
            "execute_query", create_tool_node_with_fallback([db_query_tool])
        )
        workflow.add_node("process_query_result", self.process_query_result)
        workflow.add_node("generate_answer", self.generate_answer_node)
        # 엣지 연결
        workflow.add_edge(START, "first_tool_call")
        workflow.add_edge("first_tool_call", "list_tables_tool")
        workflow.add_edge("list_tables_tool", "model_get_schema")
        workflow.add_edge("model_get_schema", "get_schema_tool")
        workflow.add_edge("get_schema_tool", "query_gen")
        workflow.add_conditional_edges("query_gen", self.should_continue)
        workflow.add_edge("correct_query", "execute_query")
        workflow.add_edge("execute_query", "process_query_result")
        workflow.add_edge("process_query_result", "query_gen")
        workflow.add_edge("generate_answer", END)

        # 그래프 컴파일
        self.app = workflow.compile(checkpointer=MemorySaver())

    # 첫 번째 도구 호출을 위한 노드 정의
    def first_tool_call(self, state: State) -> dict[str, list[AIMessage]]:
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "sql_db_list_tables",
                            "args": {},
                            "id": "initial_tool_call_abc123",
                        }
                    ],
                )
            ]
        }

    # 쿼리 정확성 체크 함수
    def model_check_query(self, state: State) -> dict[str, list[AIMessage]]:
        """쿼리 정확성을 체크하는 함수"""
        last_message = state["messages"][-1]
        query_content = last_message.content

        # "Answer: ```sql" 형식에서 SQL 쿼리 추출
        if query_content.startswith("Answer:"):
            # SQL 코드 블록에서 쿼리 추출
            if "```sql" in query_content:
                sql_start = query_content.find("```sql") + 6
                sql_end = query_content.find("```", sql_start)
                if sql_end > sql_start:
                    query_content = query_content[sql_start:sql_end].strip()
            # 또는 Answer: SELECT ... 형식에서 추출
            elif "SELECT " in query_content:
                query_content = query_content.replace("Answer:", "").strip()

            # logger.info(f"model_check_query 추출된 SQL 쿼리: {query_content[:100]}...")

            # 추출된 쿼리로 AIMessage 생성
            query_message = AIMessage(content=query_content)
            return {"messages": [query_check.invoke({"messages": [query_message]})]}

        # 일반적인 경우
        return {"messages": [query_check.invoke({"messages": [last_message]})]}

    # 쿼리 생성 노드 정의
    def query_gen_node(self, state: State):
        try:
            # 이전 메시지에 이미 쿼리 결과가 있는지 확인
            for message in reversed(state["messages"][:-1]):  # 마지막 메시지 제외
                if (
                    hasattr(message, "name")
                    and message.name == "db_query_tool"
                    and hasattr(message, "content")
                    and not message.content.startswith("Error:")
                ):
                    # 쿼리 결과가 있으면 QUERY_EXECUTED_SUCCESSFULLY 반환
                    return {
                        "messages": [AIMessage(content="QUERY_EXECUTED_SUCCESSFULLY")]
                    }

            # 쿼리 생성
            message = query_gen.invoke(state)

            # 이미 답변 형식이면 그대로 반환
            if (
                hasattr(message, "content")
                and isinstance(message.content, str)
                and len(message.content) > 50  # 긴 텍스트는 답변으로 간주
                and not message.content.startswith("SELECT")
                and not message.content.startswith("Error:")
            ):
                # 답변이 "Answer:"로 시작하지 않으면 추가
                if not message.content.startswith("Answer:"):
                    message.content = f"Answer: {message.content}"
                # logger.info(f"query_gen_node 응답: {message.content}")
                return {"messages": [message]}

            # 일반적인 쿼리 또는 오류 메시지
            return {"messages": [message]}

        except Exception as e:
            logger.error(f"query_gen_node 쿼리 생성 중 오류: {str(e)}")
            return {
                "messages": [
                    AIMessage(
                        content=f"Error: 쿼리 생성 중 오류가 발생했습니다: {str(e)}"
                    )
                ]
            }

    # 쿼리 실행 결과를 처리하는 노드
    def process_query_result(self, state: State):
        last_message = state["messages"][-1]

        # 쿼리 실행 결과가 있으면 성공 신호 반환
        if (
            hasattr(last_message, "name")
            and last_message.name == "db_query_tool"
            and hasattr(last_message, "content")
        ):
            if not last_message.content.startswith("Error:"):
                logger.info("process_query_result 쿼리 실행 성공, 결과를 생성합니다.")
                return {"messages": [AIMessage(content="QUERY_EXECUTED_SUCCESSFULLY")]}
            else:
                # 오류가 발생한 경우 로그 기록
                logger.error(
                    f"process_query_result 쿼리 실행 중 오류: {last_message.content}"
                )
                return {"messages": [AIMessage(content=last_message.content)]}

        # 결과가 없거나 오류인 경우 그대로 반환
        logger.warning(
            f"process_query_result 예상치 못한 메시지 형식: {type(last_message)}"
        )
        return {"messages": [last_message]}

    # 답변 생성 노드 정의
    def generate_answer_node(self, state: State):
        try:
            # 쿼리 결과 찾기
            query_result = None
            for message in reversed(state["messages"]):
                if (
                    hasattr(message, "name")
                    and message.name == "db_query_tool"
                    and hasattr(message, "content")
                    and not message.content.startswith("Error:")
                ):
                    query_result = message.content
                    break

            if not query_result:
                return {
                    "messages": [
                        AIMessage(
                            content="Answer: 죄송합니다, 쿼리 결과를 찾을 수 없습니다."
                        )
                    ]
                }

            # 사용자 질문 찾기
            user_question = None
            for message in state["messages"]:
                if hasattr(message, "type") and message.type == "human":
                    user_question = message.content
                    break

            # 답변 생성을 위한 컨텍스트 구성
            try:
                # 답변 생성 시도
                answer_context = {
                    "messages": [
                        {
                            "role": "user",
                            "content": f"질문: {user_question}\n\n쿼리 결과: {query_result}",
                        }
                    ]
                }

                # 직접 LLM 호출 후 결과 처리
                llm_response = answer_gen.invoke(
                    {"messages": answer_context["messages"]}
                )
                # logger.info(f"generate_answer_node 응답: {llm_response}")
                # logger.info(f"generate_answer_node 응답 타입: {type(llm_response)}")

                # 일반적인 AIMessage 응답인 경우
                if hasattr(llm_response, "content"):
                    content = llm_response.content
                    if isinstance(content, dict) and "answer" in content:
                        # 답변용 메타데이터를 담은 content를 특별 처리
                        # 이 데이터는 직접 반환하지 않고 AIMessage의 additional_kwargs에 저장
                        answer_msg = AIMessage(content=f"Answer: {content['answer']}")
                        answer_msg.additional_kwargs["result_data"] = content
                        return {"messages": [answer_msg]}
                    else:
                        # 일반 텍스트 응답
                        if isinstance(content, str) and not content.startswith(
                            "Answer:"
                        ):
                            content = f"Answer: {content}"
                        return {"messages": [AIMessage(content=content)]}

                # JSON 형식의 딕셔너리인 경우 (직접 반환된 경우)
                elif isinstance(llm_response, dict) and "answer" in llm_response:
                    # 답변용 메타데이터를 담은 딕셔너리
                    answer_msg = AIMessage(content=f"Answer: {llm_response['answer']}")
                    answer_msg.additional_kwargs["result_data"] = llm_response
                    return {"messages": [answer_msg]}

                # 기타 타입 (문자열, 리스트 등)
                else:
                    content = (
                        str(llm_response)
                        if llm_response
                        else "응답을 생성할 수 없습니다."
                    )
                    if not content.startswith("Answer:"):
                        content = f"Answer: {content}"
                    return {"messages": [AIMessage(content=content)]}

            except Exception as e:
                # LLM 호출 실패 시 기본 응답
                content = f"Answer: 죄송합니다, 쿼리 결과를 해석하는 중 오류가 발생했습니다: {str(e)}"
                return {"messages": [AIMessage(content=content)]}

        except Exception as e:
            return {
                "messages": [
                    AIMessage(
                        content=f"Answer: 죄송합니다, 답변 생성 중 오류가 발생했습니다: {str(e)}"
                    )
                ]
            }

    # 조건부 엣지 정의
    def should_continue(
        self,
        state: State,
    ) -> Literal[END, "correct_query", "query_gen", "generate_answer"]:
        last_message = state["messages"][-1]

        # 메시지 내용이 있는 경우
        if hasattr(last_message, "content") and isinstance(last_message.content, str):
            # 1) SQL 쿼리인 경우 쿼리 검증 노드로 이동
            if last_message.content.startswith("Answer: ```sql") or (
                last_message.content.startswith("Answer:")
                and "SELECT " in last_message.content
            ):
                # logger.info(
                #     "should_continue SQL 쿼리가 감지되었습니다. 쿼리 검증을 위해 이동합니다."
                # )
                return "correct_query"
            # 2) 일반적인 "Answer:" 메시지는 종료
            elif (
                last_message.content.startswith("Answer:")
                and "sql" not in last_message.content.lower()
            ):
                return END
            # 3) 쿼리가 성공적으로 실행되었으면 답변 생성 노드로 이동
            elif last_message.content == "QUERY_EXECUTED_SUCCESSFULLY":
                return "generate_answer"
            # 4) 오류가 있으면 쿼리 생성 노드로 돌아감
            elif last_message.content.startswith("Error:"):
                return "query_gen"
            # 5) 일반 텍스트 응답이 있으면 (영어로 된 답변 등) 종료
            elif len(last_message.content) > 20 and not last_message.content.startswith(
                "SELECT"
            ):
                return END

        # 6) 반복 횟수 제한을 위한 안전장치
        if len(state["messages"]) > 20:
            return END

        # 기본적으로 쿼리 검증 노드로 이동
        return "correct_query"

    def random_uuid(self):
        """랜덤 UUID를 생성합니다."""
        return str(uuid.uuid4())

    def run_agent(self, query: str):
        """
        사용자 질의를 받아 에이전트를 실행하고 결과를 반환합니다.

        Args:
            query (str): 사용자 질의

        Returns:
            dict: 에이전트 실행 결과
        """
        try:
            # 에이전트 직접 실행
            # logger.info(f"run_agent 에이전트 실행: {query}")

            # 직접 app.invoke 호출
            result = self.app.invoke(
                {"messages": [HumanMessage(content=query)]},
                RunnableConfig(
                    recursion_limit=10, configurable={"thread_id": self.random_uuid()}
                ),
            )

            # 결과 처리
            if "messages" in result and result["messages"]:
                last_message = result["messages"][-1]
                # logger.info(f"run_agent 최종 메시지: {last_message}")

                # AIMessage의 additional_kwargs에 result_data가 있는 경우 처리
                if (
                    hasattr(last_message, "additional_kwargs")
                    and "result_data" in last_message.additional_kwargs
                ):
                    # logger.info(
                    #     f"additional_kwargs에서 result_data 발견: {last_message.additional_kwargs['result_data']}"
                    # )
                    return last_message.additional_kwargs["result_data"]

                # result 키가 있는 메시지 처리 (이전 버전 호환성 유지)
                if (
                    hasattr(last_message, "content")
                    and isinstance(last_message.content, dict)
                    and "result" in last_message.content
                ):
                    # logger.info(f"result 키를 가진 응답 발견: {last_message.content}")
                    return last_message.content["result"]

                # 메시지가 AIMessage 객체인 경우 (일반 텍스트 응답)
                if hasattr(last_message, "content") and isinstance(
                    last_message.content, str
                ):
                    content = last_message.content

                    # "Answer:" 형식의 텍스트 응답인 경우
                    if content.startswith("Answer:"):
                        # "Answer:" 접두사 제거
                        clean_answer = content.replace("Answer:", "", 1).strip()
                        # logger.info(
                        #     f"run_agent 처리된 최종 응답: {clean_answer[:100]}..."
                        # )
                        return {"answer": clean_answer, "infos": []}
                    else:
                        # 그 외 텍스트 응답
                        # logger.info(
                        #     f"run_agent 처리된 최종 응답 (기본): {content[:100]}..."
                        # )
                        return {"answer": content, "infos": []}

            # 적절한 결과가 없는 경우
            return {"answer": "응답을 처리하는 중 오류가 발생했습니다.", "infos": []}

        except Exception as e:
            logger.error(f"run_agent 에이전트 실행 중 오류: {str(e)}")
            return {"error": str(e)}
