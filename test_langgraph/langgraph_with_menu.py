from typing import Any, Annotated, Literal, List, Callable
from langchain_core.messages import ToolMessage, AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableLambda, RunnableWithFallbacks
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode
from langgraph.graph import END, StateGraph, START
from langgraph.graph.message import AnyMessage, add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from typing_extensions import TypedDict
import uuid

from dotenv import load_dotenv
import logging

load_dotenv()

# Connect to the database
db = SQLDatabase.from_uri("sqlite:///../meokten/meokten.db")


# Error handling function
def handle_tool_error(state) -> dict:
    # Check error information
    error = state.get("error")
    # Check tool information
    tool_calls = state["messages"][-1].tool_calls
    # Wrap with ToolMessage and return
    return {
        "messages": [
            ToolMessage(
                content=f"Here is the error: {repr(error)}\n\nPlease fix your mistakes.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
    }


# Create a ToolNode to handle errors and surface them to the agent
def create_tool_node_with_fallback(tools: list) -> RunnableWithFallbacks[Any, dict]:
    """
    Create a ToolNode with a fallback to handle errors and surface them to the agent.
    """
    # Add fallback behavior for error handling to the ToolNode
    return ToolNode(tools).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )


# Create SQLDatabaseToolkit
toolkit = SQLDatabaseToolkit(db=db, llm=ChatOpenAI(model="gpt-4o"))

# Get the list of available tools from the SQLDatabaseToolkit
tools = toolkit.get_tools()

# Select the tool for listing available tables in the database
list_tables_tool = next(tool for tool in tools if tool.name == "sql_db_list_tables")

# Select the tool for retrieving the DDL of a specific table
get_schema_tool = next(tool for tool in tools if tool.name == "sql_db_schema")


# Query execution tool
@tool
def db_query_tool(query: str) -> str:
    """
    Run SQL queries against a database and return results
    Returns an error message if the query is incorrect
    If an error is returned, rewrite the query, check, and retry
    """
    # Execute query
    result = db.run_no_throw(query)

    # Error: Return error message if no result
    if not result:
        return "Error: Query failed. Please rewrite your query and try again."
    # Success: Return the query execution result
    return result


# Define a system message to check SQL queries for common mistakes
query_check_system = """You are a SQL expert with a strong attention to detail.
Double check the SQLite query for common mistakes, including:
- Using NOT IN with NULL values
- Using UNION when UNION ALL should have been used
- Using BETWEEN for exclusive ranges
- Data type mismatch in predicates
- Properly quoting identifiers
- Using the correct number of arguments for functions
- Casting to the correct data type
- Using the proper columns for joins

If there are any of the above mistakes, rewrite the query. If there are no mistakes, just reproduce the original query.

You will call the appropriate tool to execute the query after running this check."""

# Create the prompt
query_check_prompt = ChatPromptTemplate.from_messages(
    [("system", query_check_system), ("placeholder", "{messages}")]
)

# Create the Query Checker chain
query_check = query_check_prompt | ChatOpenAI(model="gpt-4o", temperature=0).bind_tools(
    [db_query_tool], tool_choice="db_query_tool"
)


# Define the agent's state
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


# Create a new graph
workflow = StateGraph(State)


# Add a node for the first tool call
def first_tool_call(state: State) -> dict[str, list[AIMessage]]:
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


# Define a function to check query accuracy with a model
def model_check_query(state: State) -> dict[str, list[AIMessage]]:
    """
    Use this tool to check that your query is correct before you run it
    """
    return {"messages": [query_check.invoke({"messages": [state["messages"][-1]]})]}


# Add a node for the first tool call
workflow.add_node("first_tool_call", first_tool_call)

# Add nodes for the first two tools
workflow.add_node(
    "list_tables_tool", create_tool_node_with_fallback([list_tables_tool])
)
workflow.add_node("get_schema_tool", create_tool_node_with_fallback([get_schema_tool]))

# Add a model node to select relevant tables based on the question and available tables
model_get_schema = ChatOpenAI(model="gpt-4o", temperature=0).bind_tools(
    [get_schema_tool]
)
workflow.add_node(
    "model_get_schema",
    lambda state: {
        "messages": [model_get_schema.invoke(state["messages"])],
    },
)

# Add a model node to generate a query based on the question and schema
QUERY_GEN_INSTRUCTION = """You are a SQL expert with a strong attention to detail.

You can define SQL queries, analyze queries results and interpretate query results to response an answer.

Read the messages bellow and identify the user question, table schemas, query statement and query result, or error if they exist.

1. If there's not any query result that make sense to answer the question, create a syntactically correct SQLite query to answer the user question. DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.) to the database.

2. If you create a query, response ONLY the query statement. For example, "SELECT id, name FROM pets;"

3. If a query was already executed, but there was an error. Response with the same error message you found. For example: "Error: Pets table doesn't exist"

4. If a query was already executed successfully interpretate the response and answer the question following this pattern: Answer: <<question answer>>. 
    For example: "Answer: There three cats registered as adopted"
"""

query_gen_prompt = ChatPromptTemplate.from_messages(
    [("system", QUERY_GEN_INSTRUCTION), ("placeholder", "{messages}")]
)

query_gen = query_gen_prompt | ChatOpenAI(model="gpt-4o", temperature=0)


# Define conditional edges
def should_continue(
    state: State,
) -> Literal[END, "correct_query", "query_gen", "process_results"]:
    message = state["messages"][-1].content

    # 1) Terminate if the message starts with "Answer:"
    if message.startswith("Answer:"):
        return "process_results"

    # 2) Follow existing logic for other cases
    elif message.startswith("Error:"):
        return "query_gen"
    else:
        return "correct_query"


# Define the query generation node
def query_gen_node(state: State):
    message = query_gen.invoke(state)

    # If the LLM makes incorrect tool calls, return error messages
    tool_messages = []
    if hasattr(message, "tool_calls") and message.tool_calls:
        for tc in message.tool_calls:
            tool_messages.append(
                ToolMessage(
                    content=f"Error: The wrong tool was called: {tc['name']}. Please fix your mistakes. Remember to only call SubmitFinalAnswer to submit the final answer. Generated queries should be outputted WITHOUT a tool call.",
                    tool_call_id=tc["id"],
                )
            )
    else:
        tool_messages = []
    return {"messages": [message] + tool_messages}


# Define the process_results node to fetch menu information and format the final answer
def process_results_node(state: State):
    # Get the last message which should contain the query results
    last_message = state["messages"][-1]
    content = last_message.content

    # If the message already starts with "Answer:", just return it
    if content.startswith("Answer:"):
        return {"messages": state["messages"]}

    # Parse the query results
    try:
        # Extract restaurant information from the query results
        if isinstance(content, str) and "SELECT" in content.upper():
            # If the last message is a SQL query, execute it
            result = db_query_tool.invoke(content)
        else:
            # If the last message is already the result
            result = content

        # Convert result to list if it's a string
        if isinstance(result, str):
            import ast

            try:
                result = ast.literal_eval(result)
            except:
                # If we can't parse it, just return the original message
                return {
                    "messages": state["messages"]
                    + [AIMessage(content=f"Answer: {result}")]
                }

        # Process the restaurant results
        restaurants = []
        if isinstance(result, list):
            for item in result:
                if isinstance(item, tuple):
                    # Convert tuple to dict for easier processing
                    restaurant = {
                        "name": item[0],
                        "address": item[1],
                        "video_url": item[2] if len(item) > 2 else None,
                    }
                    restaurants.append(restaurant)
                else:
                    restaurants.append(item)

        # Fetch menu information for each restaurant
        for restaurant in restaurants:
            if "name" in restaurant:
                # Query to find restaurant_id
                restaurant_query = f"SELECT id FROM restaurants WHERE name = '{restaurant['name']}' LIMIT 1"
                restaurant_id_result = db_query_tool.invoke(restaurant_query)

                if restaurant_id_result and not isinstance(restaurant_id_result, str):
                    restaurant_id = (
                        restaurant_id_result[0][0] if restaurant_id_result else None
                    )
                    if restaurant_id:
                        # Query to get menus for this restaurant
                        menu_query = f"SELECT menu_name, menu_type, menu_review FROM menus WHERE restaurant_id = {restaurant_id}"
                        menus = db_query_tool.invoke(menu_query)

                        if menus and not isinstance(menus, str):
                            restaurant["menus"] = []
                            for menu in menus:
                                restaurant["menus"].append(
                                    {
                                        "name": menu[0],
                                        "type": menu[1],
                                        "review": menu[2],
                                    }
                                )

        # Use LLM to generate a more natural response
        if restaurants:
            # Prepare restaurant data for the LLM
            restaurant_data = []
            for idx, restaurant in enumerate(restaurants, 1):
                restaurant_info = {
                    "name": restaurant.get("name", "이름 없음"),
                    "address": restaurant.get("address", ""),
                    "video_url": restaurant.get("video_url", ""),
                    "menus": [],
                }

                if "menus" in restaurant and restaurant["menus"]:
                    for menu in restaurant["menus"][:3]:
                        menu_info = {
                            "name": menu.get("name", ""),
                            "type": menu.get("type", ""),
                            "review": menu.get("review", ""),
                        }
                        restaurant_info["menus"].append(menu_info)

                restaurant_data.append(restaurant_info)

            # Create a prompt for the LLM
            response_prompt = f"""
            사용자가 "{state['messages'][0].content}"라고 질문했습니다.
            
            다음은 검색된 식당 정보입니다:
            {restaurant_data}
            
            이 정보를 바탕으로 사용자에게 자연스러운 답변을 제공해주세요.
            각 식당의 이름, 주소, 대표 메뉴를 포함하고, 메뉴에 대한 간단한 설명도 추가해주세요.
            식당을 추천하는 이유도 간략하게 설명해주세요.
            답변은 반드시 "Answer:"로 시작해야 합니다.
            """

            # Call LLM to generate the response
            llm = ChatOpenAI(model="gpt-4o", temperature=0.7)
            llm_response = llm.invoke(response_prompt)

            # Ensure the response starts with "Answer:"
            final_answer = llm_response.content
            if not final_answer.startswith("Answer:"):
                final_answer = f"Answer: {final_answer}"
        else:
            final_answer = "Answer: 검색 결과가 없습니다. 다른 검색어로 시도해보세요."

        return {"messages": state["messages"] + [AIMessage(content=final_answer)]}

    except Exception as e:
        # If there's an error, return a generic answer
        return {
            "messages": state["messages"]
            + [AIMessage(content=f"Answer: 결과 처리 중 오류가 발생했습니다: {str(e)}")]
        }


# Add the query generation node
workflow.add_node("query_gen", query_gen_node)

# Add a node to check the query with the model before execution
workflow.add_node("correct_query", model_check_query)

# Add a node to execute the query
workflow.add_node("execute_query", create_tool_node_with_fallback([db_query_tool]))

# Add the process_results node
workflow.add_node("process_results", process_results_node)

# Specify edges between nodes
workflow.add_edge(START, "first_tool_call")
workflow.add_edge("first_tool_call", "list_tables_tool")
workflow.add_edge("list_tables_tool", "model_get_schema")
workflow.add_edge("model_get_schema", "get_schema_tool")
workflow.add_edge("get_schema_tool", "query_gen")
workflow.add_conditional_edges(
    "query_gen",
    should_continue,
    {
        "correct_query": "correct_query",
        "query_gen": "query_gen",
        "process_results": "process_results",
    },
)
workflow.add_edge("correct_query", "execute_query")
workflow.add_edge("execute_query", "process_results")
workflow.add_edge("process_results", END)

# Compile the workflow into an executable app
app = workflow.compile(checkpointer=MemorySaver())


def random_uuid():
    return str(uuid.uuid4())


def invoke_graph(
    graph,
    inputs: dict,
    config,
    node_names: List[str] = [],
    callback: Callable = None,
):
    logger = logging.getLogger(__name__)

    # Create a thread to run the graph
    thread = graph.stream(inputs, config)

    # Iterate through the thread
    for chunk in thread:
        # Get the node name
        node_name = chunk.get("node_name", "")

        # Skip if not in node_names
        if node_names and node_name not in node_names:
            continue

        # Get the output
        output = chunk.get("output", {})

        # Format the output
        if "messages" in output:
            messages = output["messages"]
            if messages:
                last_message = messages[-1]
                if hasattr(last_message, "content"):
                    content = last_message.content
                    # Log the content
                    logger.info(f"[{node_name}] {content[:100]}...")

                    # Call the callback if provided
                    if callback:
                        callback(node_name, content)

    # Get the final output
    final_output = thread.output

    # Log the final output
    if "messages" in final_output:
        messages = final_output["messages"]
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, "content"):
                content = last_message.content
                logger.info(f"[FINAL] {content[:100]}...")

    return final_output


# 사용 예시
if __name__ == "__main__":
    output = invoke_graph(
        app,
        {
            "messages": [HumanMessage(content="논현역 한식 맛집 추천해줘")],
        },
        {"recursion_limit": 30, "configurable": {"thread_id": random_uuid()}},
    )
