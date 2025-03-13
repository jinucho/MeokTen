import json
import uuid
from typing import Any, Callable, List, Literal

from agent.config import LLM, State, get_logger
from agent.prompt_chains import answer_gen, query_check, query_gen

# 내부 모듈 import
from agent.tools import (
    create_tool_node_with_fallback,
    db_query_tool,
    get_schema_tool,
    list_tables_tool,
)
from IPython.display import Image
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.graph import MermaidDrawMethod
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

            logger.info(f"추출된 SQL 쿼리: {query_content[:100]}...")

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
                logger.info(f"query_gen_node 응답: {message.content}")
                return {"messages": [message]}

            # 일반적인 쿼리 또는 오류 메시지
            return {"messages": [message]}

        except Exception as e:
            logger.error(f"쿼리 생성 중 오류: {str(e)}")
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
                logger.info("쿼리 실행 성공, 결과를 생성합니다.")
                return {"messages": [AIMessage(content="QUERY_EXECUTED_SUCCESSFULLY")]}
            else:
                # 오류가 발생한 경우 로그 기록
                logger.error(f"쿼리 실행 중 오류: {last_message.content}")
                return {"messages": [AIMessage(content=last_message.content)]}

        # 결과가 없거나 오류인 경우 그대로 반환
        logger.warning(f"예상치 못한 메시지 형식: {type(last_message)}")
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
                logger.info(f"answer_gen 응답: {llm_response}")
                logger.info(f"answer_gen 응답 타입: {type(llm_response)}")

                # 응답 타입에 따른 처리
                content = ""
                if isinstance(llm_response, dict):
                    content = llm_response
                    
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
                logger.info("SQL 쿼리가 감지되었습니다. 쿼리 검증을 위해 이동합니다.")
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

    def invoke_graph(
        self,
        graph: Any,
        inputs: dict,
        config: RunnableConfig = None,
        node_names: List[str] = [],
        callback: Callable = None,
        return_result: bool = True,
    ):
        """
        LangGraph 앱의 실행 결과를 예쁘게 스트리밍하여 출력하는 함수입니다.

        Args:
            graph: 실행할 컴파일된 LangGraph 객체
            inputs (dict): 그래프에 전달할 입력값 딕셔너리
            config (RunnableConfig, optional): 실행 설정
            node_names (List[str], optional): 출력할 노드 이름 목록. 기본값은 빈 리스트
            callback (Callable, optional): 각 청크 처리를 위한 콜백 함수. 기본값은 None
                콜백 함수는 {"node": str, "content": str} 형태의 딕셔너리를 인자로 받습니다.
            return_result (bool, optional): 결과를 반환할지 여부. 기본값은 True

        Returns:
            dict or None: return_result가 True인 경우 최종 결과를 반환, 아니면 None 반환
        """
        if config is None:
            config = RunnableConfig(
                recursion_limit=30, configurable={"thread_id": self.random_uuid()}
            )

        def format_namespace(namespace):
            return namespace[-1].split(":")[0] if len(namespace) > 0 else "root graph"

        # 결과를 저장할 변수
        result = {}

        # subgraphs=True 를 통해 서브그래프의 출력도 포함
        for namespace, chunk in graph.stream(
            inputs, config, stream_mode="updates", subgraphs=True
        ):
            for node_name, node_chunk in chunk.items():
                # node_names가 비어있지 않은 경우에만 필터링
                if len(node_names) > 0 and node_name not in node_names:
                    continue

                # 결과 저장 (return_result가 True인 경우)
                if return_result:
                    if node_name not in result:
                        result[node_name] = []
                    result[node_name].append(node_chunk)

                # 콜백 함수가 있는 경우 실행
                if callback is not None:
                    callback({"node": node_name, "content": node_chunk})
                # 콜백이 없는 경우 기본 출력
                else:
                    logger.debug("\n" + "=" * 50)
                    formatted_namespace = format_namespace(namespace)
                    if formatted_namespace == "root graph":
                        logger.debug(f"🔄 Node: {node_name} 🔄")
                    else:
                        logger.debug(
                            f"🔄 Node: {node_name} in [{formatted_namespace}] 🔄"
                        )
                    logger.debug("- " * 25)

                    # 노드의 청크 데이터 출력
                    if isinstance(node_chunk, dict):
                        for k, v in node_chunk.items():
                            if isinstance(v, BaseMessage):
                                logger.debug(f"{v}")
                            elif isinstance(v, list):
                                for list_item in v:
                                    if isinstance(list_item, BaseMessage):
                                        logger.debug(f"{list_item}")
                                    else:
                                        logger.debug(f"{list_item}")
                            elif isinstance(v, dict):
                                for (
                                    node_chunk_key,
                                    node_chunk_value,
                                ) in node_chunk.items():
                                    logger.debug(
                                        f"{node_chunk_key}:\n{node_chunk_value}"
                                    )
                            else:
                                logger.debug(f"{k}:\n{v}")
                    else:
                        if node_chunk is not None:
                            for item in node_chunk:
                                logger.debug(f"{item}")
                    logger.debug("=" * 50)

        # 최종 결과 반환 (return_result가 True인 경우)
        if return_result:
            # 그래프의 최종 결과 가져오기
            full_result = graph.invoke(inputs, config)

            # 최종 결과에서 "Answer:"로 시작하는 마지막 메시지 또는 SubmitFinalAnswer 도구 호출 결과 추출
            final_result = {"messages": []}
            if "messages" in full_result:
                # 1. "Answer:"로 시작하는 메시지 찾기
                for message in reversed(full_result["messages"]):
                    if (
                        hasattr(message, "content")
                        and isinstance(message.content, str)
                        and message.content.startswith("Answer:")
                    ):
                        final_result["messages"] = [message]
                        break

                # 2. 최종 답변이 없는 경우 SubmitFinalAnswer 도구 호출 결과 찾기
                if not final_result["messages"]:
                    for message in reversed(full_result["messages"]):
                        if hasattr(message, "tool_calls") and message.tool_calls:
                            for tc in message.tool_calls:
                                if tc.get("name") == "SubmitFinalAnswer":
                                    # 다음 메시지가 최종 답변일 가능성이 높음
                                    idx = full_result["messages"].index(message)
                                    if idx + 1 < len(full_result["messages"]):
                                        final_result["messages"] = [
                                            full_result["messages"][idx + 1]
                                        ]
                                        break
                            if final_result["messages"]:
                                break

                # 3. 여전히 최종 답변이 없는 경우 원래 결과 사용
                if not final_result["messages"]:
                    final_result = full_result
            else:
                final_result = full_result

            return {"streaming_results": result, "final_result": final_result}

        return None

    def run_agent(
        self,
        query: str,
    ):
        """
        사용자 질의를 받아 에이전트를 실행하고 결과를 반환합니다.

        Args:
            query (str): 사용자 질의
            agent_graph: 에이전트 그래프 인스턴스 (없으면 새로 생성)

        Returns:
            dict: 에이전트 실행 결과
        """
        try:
            # 에이전트 실행
            logger.info(f"에이전트 실행: {query}")
            result = self.invoke_graph(
                graph=self.app,
                inputs={"messages": [HumanMessage(content=query)]},
                config=RunnableConfig(
                    recursion_limit=30, configurable={"thread_id": self.random_uuid()}
                ),
                return_result=True,
            )

            # 결과 처리
            if (
                result
                and "final_result" in result
                and "messages" in result["final_result"]
            ):
                messages = result["final_result"]["messages"][0].content
                logger.info(f"에이전트 실행 결과: {messages}")

                # SQL 쿼리인지 확인
                if "```sql" in messages or (
                    messages.startswith("Answer:") and "SELECT " in messages
                ):
                    logger.info("SQL 쿼리 감지, 쿼리를 직접 실행합니다.")

                    # SQL 쿼리 추출
                    sql_query = ""
                    if "```sql" in messages:
                        sql_start = messages.find("```sql") + 6
                        sql_end = messages.find("```", sql_start)
                        if sql_end > sql_start:
                            sql_query = messages[sql_start:sql_end].strip()
                    elif "SELECT " in messages:
                        sql_start = messages.find("SELECT ")
                        sql_query = messages[sql_start:].strip()

                    if sql_query:
                        logger.info(f"추출된 SQL 쿼리: {sql_query[:100]}...")
                        try:
                            # 쿼리 직접 실행
                            query_result = db_query_tool(sql_query)

                            if query_result.startswith("Error:"):
                                logger.error(f"쿼리 실행 오류: {query_result}")
                                return {
                                    "answer": f"죄송합니다. 쿼리 실행 중 오류가 발생했습니다: {query_result}",
                                    "infos": [],
                                }

                            # 쿼리 결과를 기반으로 답변 생성
                            answer_context = {
                                "messages": [
                                    {
                                        "role": "user",
                                        "content": f"질문: {query}\n\n쿼리 결과: {query_result}",
                                    }
                                ]
                            }

                            # 직접 LLM 호출 후 결과 처리
                            llm_response = answer_gen.invoke(answer_context)

                            # 응답 타입에 따른 처리
                            if hasattr(llm_response, "content"):
                                # AIMessage 객체인 경우
                                logger.info(
                                    f"AIMessage 객체에서 content 추출: {llm_response.content[:100] if llm_response.content else '내용 없음'}"
                                )
                                response_content = llm_response.content
                            elif isinstance(llm_response, str):
                                # 문자열인 경우
                                response_content = llm_response
                            elif isinstance(llm_response, dict):
                                # 딕셔너리인 경우 직접 반환
                                logger.info(
                                    f"run_agent에서 응답이 딕셔너리 타입: {llm_response}"
                                )
                                return llm_response
                            else:
                                # 기타 타입인 경우 (딕셔너리 등)
                                logger.info(
                                    f"run_agent에서 예상치 못한 응답 타입: {type(llm_response)}"
                                )
                                return {"answer": str(llm_response), "infos": []}

                            logger.info(f"생성된 답변: {response_content[:100]}...")

                            # JSON 형식으로 파싱 시도
                            try:
                                import json

                                if (
                                    response_content.strip().startswith("{")
                                    and '"answer"' in response_content
                                ):
                                    # JSON 형식의 응답인 경우
                                    logger.info("JSON 형식 답변 반환")
                                    return json.loads(response_content)
                                else:
                                    # 일반 텍스트 응답인 경우
                                    return {"answer": response_content, "infos": []}
                            except:
                                # JSON 파싱 실패 시 텍스트로 반환
                                return {"answer": response_content, "infos": []}
                        except Exception as e:
                            logger.error(f"쿼리 실행 또는 결과 처리 중 오류: {str(e)}")
                            return {
                                "answer": "죄송합니다. 쿼리 처리 중 오류가 발생했습니다.",
                                "infos": [],
                            }
                    else:
                        # SQL 쿼리 추출 실패
                        logger.warning("SQL 쿼리 추출 실패")
                        return {
                            "answer": "죄송합니다. SQL 쿼리를 추출하는 데 실패했습니다.",
                            "infos": [],
                        }

                # "Answer:" 형식의 응답인 경우
                if messages.startswith("Answer:"):
                    # "Answer:" 접두사 제거
                    clean_answer = messages.replace("Answer:", "", 1).strip()
                    logger.info(f"처리된 최종 응답: {clean_answer[:100]}...")
                    return {"answer": clean_answer, "infos": []}
                else:
                    # 그 외의 경우는 원본 메시지 반환
                    logger.info(f"처리된 최종 응답 (기본): {messages[:100]}...")
                    return {"answer": messages, "infos": []}

        except Exception as e:
            logger.error(f"에이전트 실행 중 오류: {str(e)}")
            return {"error": str(e)}
