from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.base import BaseCheckpointSaver
from typing import Optional
import logging
import time

logger = logging.getLogger(__name__)

DB_CONNECTION_TIMEOUT = 15
DB_MAX_RETRIES = 2


class MemoryManager:
    """Memory Manager 单例类"""

    _instance: Optional['MemoryManager'] = None
    _checkpointer: Optional[BaseCheckpointSaver] = None
    _setup_done: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _try_connect_postgres(self, db_url: str):
        """尝试连接 Postgres 数据库，失败返回 None"""
        try:
            import psycopg
        except ImportError:
            logger.warning("psycopg not installed, will fallback to MemorySaver")
            return None

        last_error = None
        for attempt in range(1, DB_MAX_RETRIES + 1):
            try:
                logger.info(f"Attempting database connection (attempt {attempt}/{DB_MAX_RETRIES})")
                conn = psycopg.connect(db_url, autocommit=True, connect_timeout=DB_CONNECTION_TIMEOUT)
                logger.info(f"Database connection established on attempt {attempt}")
                return conn
            except Exception as e:
                last_error = e
                logger.warning(f"Database connection attempt {attempt} failed: {e}")
                if attempt < DB_MAX_RETRIES:
                    time.sleep(1)
        logger.error(f"All {DB_MAX_RETRIES} database connection attempts failed, last error: {last_error}")
        return None

    def _setup_schema_and_tables(self, db_url: str) -> bool:
        if self._setup_done:
            return True

        conn = self._try_connect_postgres(db_url)
        if conn is None:
            return False

        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            with conn.cursor() as cur:
                cur.execute("CREATE SCHEMA IF NOT EXISTS memory")
            conn.execute("SET search_path TO memory")
            PostgresSaver(conn).setup()
            self._setup_done = True
            logger.info("Memory schema and tables created")
            return True
        except Exception as e:
            logger.warning(f"Failed to setup schema/tables: {e}")
            return False
        finally:
            conn.close()

    def _get_db_url_safe(self) -> Optional[str]:
        try:
            from storage.database.db import get_db_url
            db_url = get_db_url()
            if db_url and db_url.strip():
                return db_url
            logger.warning("db_url is empty, will fallback to MemorySaver")
            return None
        except Exception as e:
            logger.warning(f"Failed to get db_url: {e}, will fallback to MemorySaver")
            return None

    def _create_fallback_checkpointer(self) -> MemorySaver:
        self._checkpointer = MemorySaver()
        logger.warning("Using MemorySaver as fallback checkpointer (data will not persist across restarts)")
        return self._checkpointer

    def get_checkpointer(self) -> BaseCheckpointSaver:
        if self._checkpointer is not None:
            return self._checkpointer

        db_url = self._get_db_url_safe()
        if not db_url:
            return self._create_fallback_checkpointer()

        if not self._setup_schema_and_tables(db_url):
            return self._create_fallback_checkpointer()

        if "?" in db_url:
            db_url = f"{db_url}&options=-csearch_path%3Dmemory"
        else:
            db_url = f"{db_url}?options=-csearch_path%3Dmemory"

        try:
            from psycopg_pool import AsyncConnectionPool
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            pool = AsyncConnectionPool(
                conninfo=db_url,
                timeout=DB_CONNECTION_TIMEOUT,
                min_size=1,
                max_idle=300,
                check=AsyncConnectionPool.check_connection,
            )
            self._checkpointer = AsyncPostgresSaver(pool)
            logger.info("AsyncPostgresSaver initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to create AsyncPostgresSaver: {e}, will fallback to MemorySaver")
            return self._create_fallback_checkpointer()

        return self._checkpointer


_memory_manager: Optional[MemoryManager] = None


def get_memory_saver() -> BaseCheckpointSaver:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager.get_checkpointer()