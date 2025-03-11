# utils/db_utils.py
import logging
import os
import sqlite3
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class MeoktenDB:
    """SQLite 데이터베이스 연결 및 쿼리 실행을 위한 클래스"""

    _instance = None

    @classmethod
    def get_instance(cls):
        """싱글톤 인스턴스 반환"""
        if cls._instance is None:
            cls._instance = MeoktenDB()
        return cls._instance

    def __init__(self):
        """데이터베이스 연결 초기화"""
        # 데이터베이스 파일 경로 설정
        current_dir = os.getcwd()

        # 가능한 데이터베이스 경로들
        possible_paths = [
            os.path.join(current_dir, "meokten.db"),
            os.path.join(os.path.dirname(current_dir), "meokten.db"),
            os.path.join(current_dir, "meokten", "meokten.db"),
        ]

        # 존재하는 첫 번째 경로 사용
        db_path = None
        for path in possible_paths:
            if os.path.exists(path):
                db_path = path
                logger.info(f"데이터베이스 파일 경로: {db_path}")
                break

        if db_path is None:
            db_path = os.path.join(current_dir, "meokten.db")
            logger.warning(
                f"데이터베이스 파일을 찾을 수 없어 기본 경로 사용: {db_path}"
            )

        self.db_path = db_path

        # SQLite 연결 생성
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            logger.info("데이터베이스 연결 성공")
        except Exception as e:
            logger.error(f"데이터베이스 연결 실패: {str(e)}")
            raise

    def execute_query(self, query: str) -> List[Dict[str, Any]]:
        """SQL 쿼리 실행 및 결과 반환 (딕셔너리 리스트)"""
        logger.info(f"쿼리 실행 시작: {query}")
        try:
            cursor = self.conn.cursor()
            cursor.execute(query)

            # 결과를 딕셔너리 리스트로 변환
            columns = [col[0] for col in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))

            cursor.close()
            logger.info(f"쿼리 실행 결과: {len(results)}개 행")
            return results
        except Exception as e:
            logger.error(f"쿼리 실행 중 오류: {str(e)}")
            raise

    def get_table_schema(self, table_name: str) -> str:
        """테이블 스키마 정보 반환"""
        if not isinstance(table_name, str):
            error_msg = f"테이블 이름이 문자열이 아닙니다: {type(table_name)}"
            logger.error(error_msg)
            return error_msg

        try:
            query = f"PRAGMA table_info({table_name});"
            cursor = self.conn.cursor()
            cursor.execute(query)
            columns = cursor.fetchall()
            cursor.close()

            if not columns:
                return f"테이블 '{table_name}'의 스키마 정보를 찾을 수 없습니다."

            schema = f"CREATE TABLE {table_name} (\n"
            for i, col in enumerate(columns):
                schema += f"  {col['name']} {col['type']}"
                if col["pk"] == 1:
                    schema += " PRIMARY KEY"
                if col["notnull"] == 1:
                    schema += " NOT NULL"
                if col["dflt_value"] is not None:
                    schema += f" DEFAULT {col['dflt_value']}"
                if i < len(columns) - 1:
                    schema += ",\n"
                else:
                    schema += "\n"
            schema += ");"

            return schema
        except Exception as e:
            error_msg = f"테이블 '{table_name}'의 스키마 조회 중 오류 발생: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def get_all_tables(self) -> List[str]:
        """데이터베이스의 모든 테이블 목록을 반환합니다."""
        try:
            query = "SELECT name FROM sqlite_master WHERE type='table';"
            cursor = self.conn.cursor()
            cursor.execute(query)
            tables = [row[0] for row in cursor.fetchall()]
            cursor.close()
            logger.info(f"테이블 목록: {tables}")
            return tables
        except Exception as e:
            logger.error(f"테이블 목록 조회 중 오류 발생: {str(e)}")
            # 오류 발생 시 기본 테이블 목록 반환
            return ["restaurants", "menus"]

    def get_menus_by_restaurant_id(self, restaurant_id: int) -> List[Dict[str, Any]]:
        """식당 ID로 메뉴 정보 조회"""
        try:
            query = f"""
            SELECT * FROM menus
            WHERE restaurant_id = {restaurant_id}
            """
            return self.execute_query(query)
        except Exception as e:
            logger.error(f"메뉴 조회 중 오류 발생: {str(e)}")
            return []

    def close(self):
        """데이터베이스 연결 종료"""
        if hasattr(self, "conn") and self.conn:
            self.conn.close()
            logger.info("데이터베이스 연결 종료")


# 편의 함수: DB 인스턴스 반환
def get_db() -> MeoktenDB:
    """데이터베이스 인스턴스 반환"""
    return MeoktenDB.get_instance()
