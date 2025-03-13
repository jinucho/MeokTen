from typing import List, Callable, Any, Literal
from langchain_core.messages import BaseMessage, AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
import uuid


def random_uuid():
    return str(uuid.uuid4())


def invoke_graph(
    graph: CompiledStateGraph,
    inputs: dict,
    config: RunnableConfig,
    node_names: List[str] = [],
    callback: Callable = None,
    return_result: bool = False,
):
    """
    LangGraph 앱의 실행 결과를 예쁘게 스트리밍하여 출력하는 함수입니다.

    Args:
        graph (CompiledStateGraph): 실행할 컴파일된 LangGraph 객체
        inputs (dict): 그래프에 전달할 입력값 딕셔너리
        config (RunnableConfig): 실행 설정
        node_names (List[str], optional): 출력할 노드 이름 목록. 기본값은 빈 리스트
        callback (Callable, optional): 각 청크 처리를 위한 콜백 함수. 기본값은 None
            콜백 함수는 {"node": str, "content": str} 형태의 딕셔너리를 인자로 받습니다.
        return_result (bool, optional): 결과를 반환할지 여부. 기본값은 False

    Returns:
        dict or None: return_result가 True인 경우 최종 결과를 반환, 아니면 None 반환
    """

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
                print("\n" + "=" * 50)
                formatted_namespace = format_namespace(namespace)
                if formatted_namespace == "root graph":
                    print(f"🔄 Node: \033[1;36m{node_name}\033[0m 🔄")
                else:
                    print(
                        f"🔄 Node: \033[1;36m{node_name}\033[0m in [\033[1;33m{formatted_namespace}\033[0m] 🔄"
                    )
                print("- " * 25)

                # 노드의 청크 데이터 출력
                if isinstance(node_chunk, dict):
                    for k, v in node_chunk.items():
                        if isinstance(v, BaseMessage):
                            v.pretty_print()
                        elif isinstance(v, list):
                            for list_item in v:
                                if isinstance(list_item, BaseMessage):
                                    list_item.pretty_print()
                                else:
                                    print(list_item)
                        elif isinstance(v, dict):
                            for node_chunk_key, node_chunk_value in node_chunk.items():
                                print(f"{node_chunk_key}:\n{node_chunk_value}")
                        else:
                            print(f"\033[1;32m{k}\033[0m:\n{v}")
                else:
                    if node_chunk is not None:
                        for item in node_chunk:
                            print(item)
                print("=" * 50)

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
