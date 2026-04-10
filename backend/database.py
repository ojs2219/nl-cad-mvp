from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cad_mvp.db")

if "postgresql" in DATABASE_URL:
    # Parse URL to log connection parameters (without password)
    try:
        from urllib.parse import urlparse, unquote
        _parsed = urlparse(DATABASE_URL)
        _user = unquote(_parsed.username or "")
        _pass = unquote(_parsed.password or "")
        _host = _parsed.hostname
        _port = _parsed.port
        _db = (_parsed.path or "/postgres").lstrip("/")
        logger.warning(
            f"[DB] Connecting: user={_user!r} host={_host!r} port={_port} db={_db!r} "
            f"pass_len={len(_pass)} pass_last3={_pass[-3:] if len(_pass) >= 3 else '?'}"
        )
        # Use explicit keyword args to bypass any URL encoding issues
        import psycopg2
        from sqlalchemy.pool import QueuePool
        def _creator():
            return psycopg2.connect(
                host=_host,
                port=_port,
                dbname=_db,
                user=_user,
                password=_pass,
                sslmode="require",
                connect_timeout=10,
            )
        engine = create_engine(
            "postgresql+psycopg2://",
            creator=_creator,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=5,
        )
    except Exception as _parse_err:
        logger.error(f"[DB] URL parse error: {_parse_err}")
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
