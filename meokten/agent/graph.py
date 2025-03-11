# agent/graph.py
import logging
from typing import Annotated, Any, Dict, List, Literal, Optional, Callable
import ast

from dotenv import load_dotenv
import os
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
)
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langgraph.graph.message import AnyMessage, add_messages
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict
from langchain_core.runnables import RunnableLambda

from agent.tools import (
    db_query_tool,
    get_table_info_tool,
    list_tables_tool,
    get_menus_by_restaurant_tool,
    parse_str_to_obj,
)

load_dotenv()

# 로거 설정
logger = logging.getLogger(__name__)


# 상태 정의
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


# 에러 처리 함수
def handle_tool_error(state) -> dict:
    """도구 호출 중 에러 처리"""
    # 에러 정보 확인
    error = state.get("error")

    # 도구 호출 정보 확인
    tool_calls = state["messages"][-1].tool_calls

    # ToolMessage로 감싸서 반환
    return {
        "messages": [
            ToolMessage(
                content=f"에러 발생: {repr(error)}\n\n올바른 도구 호출을 시도하세요.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
    }


# 에러 처리를 포함한 도구 노드 생성
def create_tool_node_with_fallback(tools: list):
    """에러 처리를 포함한 도구 노드 생성"""
    return ToolNode(tools).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )


# 첫 번째 도구 호출 노드
def first_tool_call(state: State) -> dict[str, list[AIMessage]]:
    """첫 번째 도구 호출: 사용자 질문 처리"""
    logger.info("첫 번째 도구 호출 노드 실행")

    # 질문 확인
    messages = state["messages"]
    question = messages[-1].content if messages else "맛집 추천해줘"
    logger.info(f"사용자 질문: {question}")

    # 시스템 메시지 추가
    return {
        "messages": [
            AIMessage(
                content="먼저 데이터베이스의 테이블 목록을 조회하겠습니다. 사용 가능한 테이블을 확인해보겠습니다."
            )
        ]
    }


# 쿼리 확인 노드
def model_check_query(state: State) -> dict[str, list[AIMessage]]:
    """쿼리 검증 노드: 생성된 SQL 쿼리 검증"""
    logger.info("쿼리 검증 노드 실행")

    # 메시지 확인
    messages = state["messages"]

    # 쿼리 체커 프롬프트
    system_message = """
    당신은 SQL 쿼리 검증 전문가입니다. 사용자가 제공한 SQL 쿼리를 분석하고 다음 사항을 확인하세요:
    
    1. 문법 오류가 있는지 확인
    2. 테이블 이름이 올바른지 확인 (restaurants, menus만 사용 가능)
    3. 컬럼 이름이 올바른지 확인
    4. SQL 인젝션 위험이 있는지 확인
    
    오류가 있다면 수정된 쿼리를 제공하세요. 쿼리가 올바르다면 그대로 반환하세요.
    
    테이블 정보:
    - restaurants: id, name, address, latitude, longitude, station_name, video_id, video_url
    - menus: id, restaurant_id, menu_name, menu_type, price, review
    
    예시 검증:
    - 잘못된 쿼리: "SELECT * FROM users" - 'users' 테이블이 없음
    - 수정: "SELECT * FROM restaurants"
    
    결과는 ```sql 과 ``` 사이에 작성하지 말고, 직접 SQL 쿼리만 반환해주세요.
    """

    check_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_message),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    # 쿼리 체크 모델
    query_checker = check_prompt | ChatOpenAI(temperature=0)

    # 쿼리 체크 실행
    response = query_checker.invoke({"messages": messages})
    logger.info(f"쿼리 검증 결과: {response.content[:100]}...")

    # SQL 쿼리 추출
    sql_query = response.content

    # 코드 블록 제거
    if "```sql" in sql_query:
        sql_query = sql_query.split("```sql")[1].split("```")[0].strip()
    elif "```" in sql_query:
        sql_query = sql_query.split("```")[1].strip()

    # 세미콜론 제거
    if sql_query.endswith(";"):
        sql_query = sql_query[:-1]

    logger.info(f"추출된 SQL 쿼리: {sql_query}")

    # 검증된 쿼리를 포함한 메시지 반환
    return {"messages": [AIMessage(content=f"SQL 쿼리: {sql_query}")]}


# 쿼리 생성 노드
def query_gen_node(state: State):
    """쿼리 생성 노드: 사용자 질문을 SQL 쿼리로 변환"""
    logger.info("쿼리 생성 노드 실행")

    # 시스템 프롬프트
    system_prompt = """
    당신은 SQL 쿼리 생성 전문가입니다. 사용자의 질문을 분석하여 적절한 SQL 쿼리를 생성해주세요.
    
    데이터베이스 정보:
    1. restaurants 테이블:
       - id: 식당 ID (정수)
       - name: 식당 이름 (텍스트)
       - address: 주소 (텍스트)
       - latitude: 위도 (텍스트)
       - longitude: 경도 (텍스트)
       - station_name: 역 이름 (텍스트) LIKE 조건으로 검색
       - video_id: 유튜브 비디오 ID (텍스트)
       - video_url: 유튜브 비디오 URL (텍스트)
    
    2. menus 테이블:
       - id: 메뉴 ID (정수)
       - restaurant_id: 식당 ID (정수) - restaurants 테이블의 id와 연결
       - menu_name: 메뉴 이름 (텍스트)
       - menu_type: 메뉴 종류 (텍스트) - 한식, 중식, 일식, 양식 등
       - price: 가격 (정수)
       - review: 메뉴 리뷰 (텍스트)
    
    쿼리 작성 가이드라인:
    1. 위치 검색: address 또는 station_name 컬럼에 LIKE 연산자 사용 (예: address LIKE '%강남%')
    2. 메뉴 종류 검색: menu_type 컬럼 사용 (예: menu_type LIKE '%한식%')
    3. 식당과 메뉴 조인: restaurants.id = menus.restaurant_id
    4. 결과는 최대 5개로 제한: LIMIT 5 사용
    
    생성한 쿼리는 반드시 ```sql 와 ``` 사이에 작성하세요.
    
    예시:
    - 질문: "강남역 근처 맛집 추천해줘"
    - 쿼리: 
    ```sql
    SELECT * FROM restaurants WHERE address LIKE '%강남역%' OR station_name LIKE '%강남역%' LIMIT 5;
    ```
    """

    # 쿼리 생성 프롬프트
    query_gen_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    # 쿼리 생성 체인
    query_generator = query_gen_prompt | ChatOpenAI(temperature=0)

    # 쿼리 생성
    response = query_generator.invoke({"messages": state["messages"]})
    logger.info(f"쿼리 생성 결과: {response.content[:100]}...")

    return {"messages": state["messages"] + [response]}


# 쿼리 실행 노드 추가
def execute_query_node(state: State):
    """쿼리 실행 노드: SQL 쿼리 실행"""
    logger.info("쿼리 실행 노드 실행")

    # 마지막 메시지에서 SQL 쿼리 추출
    messages = state["messages"]
    last_message = messages[-1]

    if not isinstance(last_message, AIMessage):
        logger.warning(f"마지막 메시지가 AI 메시지가 아님: {type(last_message)}")
        return {
            "messages": messages + [AIMessage(content="SQL 쿼리를 찾을 수 없습니다.")]
        }

    content = last_message.content

    # SQL 쿼리 추출
    sql_query = None
    if content.startswith("SQL 쿼리:"):
        sql_query = content.replace("SQL 쿼리:", "").strip()
    elif "SELECT" in content.upper() and "FROM" in content.upper():
        sql_query = content

    if not sql_query:
        logger.warning("SQL 쿼리를 찾을 수 없습니다.")
        return {
            "messages": messages + [AIMessage(content="SQL 쿼리를 찾을 수 없습니다.")]
        }

    logger.info(f"실행할 SQL 쿼리: {sql_query}")

    # 쿼리 실행
    try:
        result = db_query_tool(sql_query)
        logger.info(f"쿼리 실행 결과: {result[:100] if result else '결과 없음'}...")

        # 결과가 없는 경우 처리
        if not result or result.strip() == "" or result == "쿼리 실행 결과가 없습니다.":
            logger.warning("쿼리 실행 결과가 없습니다.")
            return {
                "messages": messages
                + [
                    ToolMessage(
                        content='{"results": []}', tool_call_id="query_execution"
                    )
                ]
            }

        # 결과를 JSON 형식으로 변환 시도
        try:
            # 결과가 표 형식인지 확인
            if "|" in result and "-" in result:
                # 표 형식 데이터를 파싱하여 딕셔너리 리스트로 변환
                lines = result.strip().split("\n")
                if len(lines) < 3:  # 헤더, 구분선, 데이터 최소 3줄 필요
                    return {
                        "messages": messages
                        + [
                            ToolMessage(
                                content='{"results": []}',
                                tool_call_id="query_execution",
                            )
                        ]
                    }

                # 헤더 추출
                headers = [h.strip() for h in lines[0].split("|") if h.strip()]

                # 데이터 행 추출 및 변환
                results_list = []
                for line in lines[2:]:  # 첫 번째 줄은 헤더, 두 번째 줄은 구분선
                    if "|" not in line:
                        continue

                    values = [v.strip() for v in line.split("|") if v.strip() != ""]
                    if len(values) == len(headers):
                        row_dict = dict(zip(headers, values))
                        results_list.append(row_dict)

                # JSON 형식으로 변환
                import json

                json_result = json.dumps({"results": results_list})
                logger.info(f"JSON 변환 결과: {json_result[:100]}...")

                return {
                    "messages": messages
                    + [ToolMessage(content=json_result, tool_call_id="query_execution")]
                }
            else:
                # 결과가 표 형식이 아닌 경우 파싱 시도
                try:
                    # 튜플 리스트 형식인지 확인 [(id, name, address, ...)]
                    import ast

                    parsed_result = ast.literal_eval(result)

                    # 튜플 리스트를 딕셔너리 리스트로 변환
                    if isinstance(parsed_result, list) and len(parsed_result) > 0:
                        # 첫 번째 항목이 튜플인지 확인
                        if isinstance(parsed_result[0], tuple):
                            # 컬럼 이름 추정 (restaurants 테이블 기준)
                            columns = [
                                "id",
                                "name",
                                "address",
                                "latitude",
                                "longitude",
                                "station_name",
                                "video_id",
                                "video_url",
                            ]

                            # 딕셔너리 리스트 생성
                            dict_list = []
                            for item in parsed_result:
                                # 컬럼 수에 맞게 조정
                                item_dict = {}
                                for i, value in enumerate(item):
                                    if i < len(columns):
                                        item_dict[columns[i]] = value
                                    else:
                                        item_dict[f"column_{i}"] = value
                                dict_list.append(item_dict)

                            # JSON 형식으로 변환
                            import json

                            json_result = json.dumps({"results": dict_list})
                            logger.info(
                                f"튜플 리스트 변환 결과: {json_result[:100]}..."
                            )

                            return {
                                "messages": messages
                                + [
                                    ToolMessage(
                                        content=json_result,
                                        tool_call_id="query_execution",
                                    )
                                ]
                            }
                except Exception as e:
                    logger.error(f"튜플 리스트 변환 중 오류 발생: {str(e)}")

                # 그 외의 경우 빈 리스트 반환
                logger.warning("결과를 파싱할 수 없어 빈 리스트 반환")
                return {
                    "messages": messages
                    + [
                        ToolMessage(
                            content='{"results": []}', tool_call_id="query_execution"
                        )
                    ]
                }
        except Exception as e:
            logger.error(f"결과 변환 중 오류 발생: {str(e)}")
            return {
                "messages": messages
                + [
                    ToolMessage(
                        content='{"results": []}', tool_call_id="query_execution"
                    )
                ]
            }
    except Exception as e:
        error_msg = f"쿼리 실행 중 오류 발생: {str(e)}"
        logger.error(error_msg)
        return {"messages": messages + [AIMessage(content=error_msg)]}


# 결과 처리 노드
def process_results_node(state: State):
    """결과 처리 노드: 쿼리 결과에서 메뉴 정보 가져와 통합"""
    logger.info("결과 처리 노드 실행")

    # 마지막 메시지에서 쿼리 결과 가져오기
    messages = state["messages"]
    last_message = messages[-1]

    # 결과를 파이썬 객체로 변환
    try:
        # 마지막 메시지가 도구 메시지인지 확인
        if isinstance(last_message, ToolMessage):
            content = last_message.content
            logger.info(f"마지막 메시지 타입: ToolMessage, 내용 길이: {len(content)}")

            # 문자열에서 파이썬 객체로 변환
            try:
                # JSON 형식인지 확인
                import json

                results_obj = json.loads(content)

                if "results" in results_obj:
                    results = results_obj["results"]
                    logger.info(
                        f"JSON 파싱 결과: {type(results)}, 항목 수: {len(results) if isinstance(results, list) else 'not a list'}"
                    )

                    # 결과가 문자열인 경우 추가 파싱 시도
                    if isinstance(results, str):
                        try:
                            # 문자열을 파이썬 객체로 변환 시도
                            import ast

                            parsed_results = ast.literal_eval(results)
                            if isinstance(parsed_results, list):
                                results = parsed_results
                                logger.info(
                                    f"문자열 파싱 결과: {type(results)}, 항목 수: {len(results)}"
                                )
                        except Exception as e:
                            logger.error(f"문자열 파싱 중 오류 발생: {str(e)}")
                else:
                    results = []
                    logger.warning("결과에 'results' 키가 없습니다.")
            except json.JSONDecodeError:
                # JSON이 아닌 경우 parse_str_to_obj 시도
                results = parse_str_to_obj(content)
                logger.info(f"parse_str_to_obj 결과: {type(results)}")

            # 결과가 없는 경우
            if (
                not results
                or (isinstance(results, list) and len(results) == 0)
                or results == "쿼리 실행 결과가 없습니다."
            ):
                return {
                    "messages": messages
                    + [
                        AIMessage(
                            content="조건에 맞는 식당을 찾을 수 없습니다. 다른 검색어로 시도해보세요."
                        )
                    ]
                }

            # 결과 처리
            if isinstance(results, list):
                restaurants = results
                logger.info(f"식당 결과 개수: {len(restaurants)}")

                # 메뉴 정보 가져오기
                for i, restaurant in enumerate(restaurants[:5]):  # 최대 5개만 처리
                    try:
                        restaurant_id = restaurant.get("id")
                        if restaurant_id:
                            # 메뉴 정보 쿼리
                            menu_response = get_menus_by_restaurant_tool(
                                str(restaurant_id)
                            )

                            try:
                                # JSON 형식인지 확인
                                import json

                                menu_obj = json.loads(menu_response)
                                if "results" in menu_obj:
                                    menus = menu_obj["results"]
                                else:
                                    menus = []
                            except json.JSONDecodeError:
                                # JSON이 아닌 경우 parse_str_to_obj 시도
                                menus = parse_str_to_obj(menu_response)

                            if menus and isinstance(menus, list):
                                restaurant["menus"] = menus
                                logger.info(
                                    f"식당 {restaurant_id}의 메뉴 {len(menus)}개 추가됨"
                                )
                    except Exception as e:
                        logger.error(f"식당 {i}번의 메뉴 정보 처리 중 오류: {str(e)}")

                # 최종 응답 생성
                final_response = "다음과 같은 맛집을 찾았습니다:\n\n"

                for i, restaurant in enumerate(restaurants, 1):
                    logger.debug(f"식당 정보: {restaurant}")
                    final_response += f"{i}. **{restaurant[1]}**\n"
                    final_response += f"   주소: {restaurant[2]}\n"

                    if restaurant.get("video_url"):
                        final_response += f"   영상: {restaurant.get('video_url')}\n"

                    # 메뉴 정보 추가
                    if restaurant.get("menus") and len(restaurant.get("menus")) > 0:
                        final_response += "   대표 메뉴:\n"
                        for menu in restaurant.get("menus"):  # 최대 3개 메뉴만 표시
                            menu_name = menu.get("menu_name", "이름 없음")
                            menu_price = menu.get("price", "가격 정보 없음")
                            menu_review = menu.get("review", "")

                            final_response += f"     - {menu_name} ({menu_price}원)"
                            if menu_review:
                                final_response += f" - {menu_review}"
                            final_response += "\n"

                    final_response += "\n"

                return {"messages": messages + [AIMessage(content=final_response)]}
            else:
                logger.warning(f"예상치 못한 결과 타입: {type(results)}")
                return {
                    "messages": messages
                    + [
                        AIMessage(
                            content=f"쿼리 결과 처리 중 오류가 발생했습니다. 결과 형식이 예상과 다릅니다: {type(results)}"
                        )
                    ]
                }
        else:
            logger.warning(f"마지막 메시지가 도구 메시지가 아님: {type(last_message)}")
            return {
                "messages": messages
                + [
                    AIMessage(
                        content="쿼리 결과를 처리할 수 없습니다. 다시 시도해주세요."
                    )
                ]
            }

    except Exception as e:
        # 오류가 발생한 경우 일반 응답 반환
        error_msg = f"결과 처리 중 오류가 발생했습니다: {str(e)}"
        logger.error(error_msg)
        return {"messages": messages + [AIMessage(content=error_msg)]}


# 계속 진행 여부 결정 함수
def should_continue(
    state: State,
) -> Literal[END, "correct_query", "query_gen", "process_results", "execute_query"]:
    """계속 진행 여부 결정 함수: 다음 단계 결정"""
    logger.info("계속 진행 여부 결정 함수 실행")

    # 마지막 메시지 확인
    messages = state["messages"]
    last_message = messages[-1]

    # 마지막 메시지 내용 확인
    if isinstance(last_message, ToolMessage):
        # 도구 메시지인 경우 process_results로 이동
        logger.info("도구 메시지 감지됨 - 결과 처리 단계로 이동")
        return "process_results"

    if isinstance(last_message, AIMessage):
        content = last_message.content

        # SQL 쿼리가 포함된 경우 correct_query로 이동
        if "```sql" in content:
            logger.info("SQL 쿼리 감지됨 - 쿼리 검증 단계로 이동")
            return "correct_query"

        # 검증된 SQL 쿼리가 있는 경우 execute_query로 이동
        if content and "SELECT" in content.upper() and "FROM" in content.upper():
            logger.info("검증된 SQL 쿼리 감지됨 - 쿼리 실행 단계로 이동")
            return "execute_query"

    # 기본적으로 query_gen으로 이동
    logger.info("기본 흐름 - 쿼리 생성 단계로 이동")
    return "query_gen"


# 그래프 생성 함수
def create_agent_graph():
    """에이전트 그래프 생성"""
    logger.info("에이전트 그래프 생성")

    # 워크플로우 정의
    workflow = StateGraph(State)

    # 노드 추가
    workflow.add_node("first_tool_call", first_tool_call)
    workflow.add_node(
        "list_tables_tool", create_tool_node_with_fallback([list_tables_tool])
    )
    workflow.add_node(
        "get_schema_tool", create_tool_node_with_fallback([get_table_info_tool])
    )
    workflow.add_node("query_gen", query_gen_node)
    workflow.add_node("correct_query", model_check_query)
    workflow.add_node("execute_query", execute_query_node)
    workflow.add_node("process_results", process_results_node)

    # 엣지 추가
    workflow.add_edge("first_tool_call", "list_tables_tool")
    workflow.add_edge("list_tables_tool", "get_schema_tool")
    workflow.add_edge("get_schema_tool", "query_gen")

    # 조건부 엣지 추가
    workflow.add_conditional_edges(
        "query_gen",
        should_continue,
        {
            "correct_query": "correct_query",
            "query_gen": "query_gen",
            "process_results": "process_results",
            "execute_query": "execute_query",
        },
    )

    # correct_query 노드에서 execute_query 노드로 이동하는 조건부 엣지 추가
    workflow.add_conditional_edges(
        "correct_query",
        lambda state: "execute_query",
        {
            "execute_query": "execute_query",
        },
    )

    workflow.add_edge("execute_query", "process_results")
    workflow.add_edge("process_results", END)

    # 시작 노드 설정
    workflow.set_entry_point("first_tool_call")

    # 체크포인터 없이 그래프 컴파일
    return workflow.compile()


# 에이전트 실행 함수
def run_agent(question: str, graph=None) -> Dict[str, Any]:
    """에이전트 실행 함수"""
    logger.info(f"에이전트 실행 시작: {question}")

    try:
        # 그래프 생성 또는 재사용
        if graph is None:
            logger.info("새 그래프 생성")
            graph = create_agent_graph()
        else:
            logger.info("기존 그래프 사용")

        # 초기 상태 설정
        config = {"recursion_limit": 15}
        state = {"messages": [HumanMessage(content=question)]}

        # 결과 저장 변수
        final_result = {
            "response": "응답을 생성할 수 없습니다.",
            "messages": [HumanMessage(content=question)],
        }

        try:
            # 그래프 실행 - 단순화된 호출
            result = graph.invoke(state, config=config)

            # 결과 처리
            if "messages" in result:
                messages = result["messages"]

                # 마지막 메시지에서 응답 추출
                if messages and len(messages) > 0:
                    last_message = messages[-1]
                    if hasattr(last_message, "content"):
                        final_result["response"] = last_message.content
                    else:
                        logger.warning(
                            f"마지막 메시지에 content 속성이 없습니다: {type(last_message)}"
                        )
                        final_result["response"] = str(last_message)

                final_result["messages"] = messages

            return final_result

        except Exception as e:
            # 그래프 실행 중 예외 발생
            error_msg = f"그래프 실행 중 오류 발생: {str(e)}"
            logger.error(error_msg)
            final_result["response"] = error_msg
            return final_result

    except Exception as e:
        # 전체 실행 중 예외 발생
        error_msg = f"에이전트 실행 중 오류 발생: {str(e)}"
        logger.error(error_msg)
        return {
            "response": error_msg,
            "messages": [HumanMessage(content=question)],
        }
