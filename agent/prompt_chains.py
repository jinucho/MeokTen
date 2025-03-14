from operator import itemgetter

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from agent.config import LLM, Answers
from agent.tools import db_query_tool
from agent.db import get_db_connection

# 쿼리 검증을 위한 프롬프트 정의
QUERY_CHECK_SYSTEM = """You are a SQL expert with a strong attention to detail.
Double check the SQLite query for common mistakes, including:
- Using NOT IN with NULL values
- Using UNION when UNION ALL should have been used
- Using BETWEEN for exclusive ranges
- Data type mismatch in predicates
- Properly quoting identifiers
- Using the correct number of arguments for functions
- Casting to the correct data type
- Using id columns each table for joins

If there are any of the above mistakes, rewrite the query. If there are no mistakes, just reproduce the original query.

You will call the appropriate tool to execute the query after running this check."""


# 쿼리 검증 프롬프트 생성
query_check_prompt = ChatPromptTemplate.from_messages(
    [("system", QUERY_CHECK_SYSTEM), ("placeholder", "{messages}")]
)

# 쿼리 검증 체인 생성
query_check = query_check_prompt | LLM().bind_tools(
    [db_query_tool], tool_choice="db_query_tool"
)

# 쿼리 생성을 위한 프롬프트 정의
QUERY_GEN_INSTRUCTION = """당신은 세부 사항에 대한 높은 주의력을 가진 SQL 전문가입니다.

당신은 SQL 쿼리를 정의하고, 쿼리 결과를 분석하며, 이를 해석하여 질문에 대한 답변을 도출할 수 있습니다.

아래 메시지를 읽고 사용자의 질문, 테이블 스키마, 쿼리문, 그리고 쿼리 결과 또는 오류가 있는지 식별하세요.

사용자 질문에서 지영명은 적절하게 추출해서 사용하세요.(예: 서울시 -> 서울, 경기도 -> 서울)

menu_type은 결과에 따라 적절하게 변형해서 사용하세요.(예: 멕시코 -> 멕시칸, 중국집 -> 중식, 일본 음식 -> 일식 등...)

1. 질문에 대한 적절한 쿼리 결과가 존재하지 않는 경우, 사용자의 질문을 해결할 수 있는 SQL 구문적으로 올바른 SQLite 쿼리를 생성하세요. 단, 데이터베이스에 영향을 주는 DML 문(INSERT, UPDATE, DELETE, DROP 등)은 절대 사용하지 마세요.

2. 새로운 쿼리를 생성할 경우, 오직 쿼리문만 반환해야 하며, 반드시 '=' 대신 LIKE 연산자를 사용해야 합니다. 또한, 'restaurants' 테이블과 'menus' 테이블을 LEFT JOIN으로 조인해야 합니다.
    그리고 쿼리에서 모든 컬럼의 이름을 명시적으로 호출해야 합니다.
    예를 들어:
    "SELECT r.id AS restaurant_id, r.name AS restaurant_name, r.address, r.station_name, r.lat, r.lng, r.review, 
    m.id AS menu_id, m.restaurant_id AS menu_restaurant_id, m.menu_name AS menu_name 
    FROM restaurants r LEFT JOIN menus m ON r.id = m.restaurant_id 
    WHERE r.station_name LIKE '%논현역%' or r.address LIKE '%논현동%';"

3. 이미 실행된 쿼리가 오류를 발생시킨 경우, 동일한 오류 메시지를 그대로 반환하세요.
    예를 들어: "Error: Pets 테이블이 존재하지 않습니다."

4. 쿼리가 성공적으로 실행되었을 경우, 쿼리의 결과를 컬럼명과 모든 정보를 그대로 반환하세요:
    "Answer: <<쿼리의 결과>>"
    예를 들어: "Answer: restaurant_id, restaurant_name, address, station_name, lat, lng, review, menu_id, menu_restaurant_id, menu_name
    (1, '논현동 맛집', '논현동', '논현역', 37.514352, 127.014352, '맛집 후기', 1, 1, '피자'),
    (2, '논현동 맛집', '논현동', '논현역', 37.514352, 127.014352, '맛집 후기', 2, 1, '스테이크')"
    
Here is Table information:
{table_info}
"""

# 쿼리 생성 프롬프트 생성
query_gen_prompt = ChatPromptTemplate.from_messages(
    [("system", QUERY_GEN_INSTRUCTION), ("placeholder", "{messages}")]
).partial(table_info=get_db_connection()[0].get_table_info())

# 쿼리 생성 체인 생성
query_gen = query_gen_prompt | LLM()

# 답변 생성을 위한 프롬프트 정의
ANSWER_GEN_INSTRUCTION = """당신은 SQL 쿼리 결과를 해석하여 사용자에게 친절하고 명확한 답변을 제공하는 전문가입니다.
제공되는 정보들은 성시경의 유튜브 영상 중 "먹을텐데"에 대한 정보들 입니다.

주어진 쿼리 결과를 분석하고, 사용자의 질문에 직접적으로 답변해주세요.

주어진 쿼리 정보를 누락시키지 마세요.

사용자와의 대화 내용:
{input}

답변 작성 시 다음 사항을 지켜주세요:
1. 식당 정보를 제공할 때는 이름, 주소, 지하철역을 제공 해주세요.
2. 식당의 메뉴들과 후기를 충분하게 제공 해주세요.
3. 쿼리 결과에서 restaurant_id가 같은 여러 행이 있다면, 이는 하나의 식당에 여러 메뉴가 있다는 의미입니다. 이런 경우 식당 정보는 한 번만 표시하고, 모든 메뉴를 함께 나열해주세요.
4. 정보가 부족한 경우, 찾을 수 없다는 메시지를 제공 해주세요.
5. 사용자가 이해하기 쉬운 자연스러운 한국어로 답변하세요.

출력 형식:

{{
    "answer": "아주 간단한 답변 내용",
    "infos": [
        {{
            "name": "식당 이름",
            "address": "식당 주소",
            "subway": "식당 지하철역",
            "lat": "식당 위도",
            "lng": "식당 경도",
            "menu": "메뉴1, 메뉴2, ...",
            "review": "식당 후기"
        }}
    ]
}}
"""

# 답변 생성 프롬프트 생성
answer_gen_prompt = ChatPromptTemplate.from_template(ANSWER_GEN_INSTRUCTION)

# 답변 생성 체인 생성
answer_gen = (
    {"input": itemgetter("messages")}
    | answer_gen_prompt
    | LLM()
    | JsonOutputParser(pydantic_object=Answers)
)
