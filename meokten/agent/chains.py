from operator import itemgetter

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from agent.config import LLM, Answers
from agent.tools import db_query_tool

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
- Using the proper columns for joins
- Using '=' operator for string comparisons when LIKE would be more appropriate
- Missing JOIN operations when querying for restaurant information (should include menus table)
- Using * instead of explicit column selection when joining tables (can cause column name conflicts)

Prefer using LIKE operator instead of '=' for string comparisons to allow for more flexible matching. For example, use "WHERE name LIKE '%keyword%'" instead of "WHERE name = 'keyword'".

CRITICAL: When checking queries related to restaurant searches, ensure that both 'restaurants' and 'menus' tables are being queried using a JOIN operation. If a query only selects from the 'restaurants' table without joining with 'menus', you MUST modify it to include a LEFT JOIN with the 'menus' table with explicit column selection.

For example, change:
```
SELECT * FROM restaurants WHERE station_name LIKE '%논현역%';
```

To:
```
SELECT 
    r.id AS restaurant_id, 
    r.name AS restaurant_name, 
    r.address, 
    r.station_name, 
    r.lat, 
    r.lng, 
    r.review,
    m.id AS menu_id, 
    m.restaurant_id AS menu_restaurant_id, 
    m.name AS menu_name, 
    m.price
FROM restaurants r
LEFT JOIN menus m ON r.id = m.restaurant_id
WHERE r.station_name LIKE '%논현역%';
```

Also, change:
```
SELECT r.*, m.* FROM restaurants r LEFT JOIN menus m ON r.id = m.restaurant_id WHERE r.station_name LIKE '%논현역%';
```

To:
```
SELECT 
    r.id AS restaurant_id, 
    r.name AS restaurant_name, 
    r.address, 
    r.station_name, 
    r.lat, 
    r.lng, 
    r.review,
    m.id AS menu_id, 
    m.restaurant_id AS menu_restaurant_id, 
    m.name AS menu_name, 
    m.price
FROM restaurants r
LEFT JOIN menus m ON r.id = m.restaurant_id
WHERE r.station_name LIKE '%논현역%';
```

This explicit column selection ensures that both restaurant information and menu details are clearly included in the results without any column name conflicts.

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
QUERY_GEN_INSTRUCTION = """You are a SQL expert with a strong attention to detail.

You can define SQL queries to retrieve information from a database.

Read the messages below and identify the user question, table schemas, and any previous query results or errors.

IMPORTANT: Only use tables and columns that are explicitly mentioned in the schema information provided. Do NOT assume the existence of any tables or columns that are not explicitly shown in the schema.

The database only has two tables: 'restaurants' and 'menus'. Do not try to query any other tables.

When writing queries, prefer using the LIKE operator instead of '=' for string comparisons to allow for more flexible matching. For example, use "WHERE name LIKE '%keyword%'" instead of "WHERE name = 'keyword'".

IMPORTANT: you MUST ALWAYS query BOTH the 'restaurants' AND 'menus' tables using a JOIN operation. NEVER query only the restaurants table. 

The format like this:
SELECT 
    r.id AS restaurant_id, 
    r.name AS restaurant_name, 
    r.address, 
    r.station_name, 
    r.lat, 
    r.lng, 
    r.review,
    m.id AS menu_id, 
    m.restaurant_id AS menu_restaurant_id, 
    m.name AS menu_name, 
    m.price
FROM restaurants r
LEFT JOIN menus m ON r.id = m.restaurant_id
WHERE r.station_name LIKE '%station_name%'

This explicit column selection ensures that both restaurant information and menu details are clearly included in the results without any column name conflicts.

Your task is to:

1. If there's not any query result that makes sense to answer the question, create a syntactically correct SQLite query to answer the user question. DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.) to the database.

2. When creating queries, you MUST ALWAYS use JOIN operations between restaurants and menus tables when searching for restaurants. NEVER query only the restaurants table.

3. If you create a query, response ONLY with the query statement. For example, "SELECT r.id AS restaurant_id, r.name AS restaurant_name, r.address, r.station_name, r.lat, r.lng, r.review, m.id AS menu_id, m.restaurant_id AS menu_restaurant_id, m.name AS menu_name, m.price FROM restaurants r LEFT JOIN menus m ON r.id = m.restaurant_id WHERE r.station_name LIKE '%논현역%';"

4. If a query was already executed, but there was an error, respond with the same error message you found. For example: "Error: restaurants table doesn't exist"

5. If a query was already executed successfully, DO NOT create a new query. Instead, respond with "QUERY_EXECUTED_SUCCESSFULLY" so the system knows to proceed to the answer generation step.

6. If you encounter any issues that prevent you from creating a valid query, respond with "Error: [explanation of the issue]"
"""

# 쿼리 생성 프롬프트 생성
query_gen_prompt = ChatPromptTemplate.from_messages(
    [("system", QUERY_GEN_INSTRUCTION), ("placeholder", "{messages}")]
)

# 쿼리 생성 체인 생성
query_gen = query_gen_prompt | LLM()

# 답변 생성을 위한 프롬프트 정의
ANSWER_GEN_INSTRUCTION = """당신은 SQL 쿼리 결과를 해석하여 사용자에게 친절하고 명확한 답변을 제공하는 전문가입니다.
제공되는 정보들은 성시경의 유튜브 영상 중 "먹을텐데"에 대한 정보들 입니다.

주어진 쿼리 결과를 분석하고, 사용자의 질문에 직접적으로 답변해주세요.

사용자와의 대화 내용:
{input}

답변 작성 시 다음 사항을 지켜주세요:
1. 맛집 정보를 제공할 때는 이름, 주소, 지하철역을 제공 해주세요.
2. 식당의 메뉴들과 후기를 충분하게 제공 해주세요. 메뉴 정보는 menu_name과 price 필드에서 추출해야 합니다.
3. 쿼리 결과에서 restaurant_id가 같은 여러 행이 있다면, 이는 하나의 식당에 여러 메뉴가 있다는 의미입니다. 이런 경우 식당 정보는 한 번만 표시하고, 모든 메뉴를 함께 나열해주세요.
4. 정보가 부족한 경우, 찾을 수 없다는 메시지를 제공 해주세요.
5. 사용자가 이해하기 쉬운 자연스러운 한국어로 답변하세요.

중요: 쿼리 결과에 menu_name과 price 필드가 있다면, 이 정보를 반드시 포함시켜 메뉴 정보를 제공해야 합니다. 메뉴 정보가 없는 경우에만 "메뉴 정보가 없습니다"라고 표시하세요.

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
            "menu": "메뉴1: 가격, 메뉴2: 가격, ...",
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
