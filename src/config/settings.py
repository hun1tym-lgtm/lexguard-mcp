"""
설정 관리
로깅, FastAPI, FastMCP 앱 초기화
"""
from typing import Any


import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from dotenv import load_dotenv
from contextlib import asynccontextmanager

# Load .env file
load_dotenv()


def setup_logging() -> logging.Logger:
    """로깅 설정"""
    logger = logging.getLogger("lexguard-mcp")
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        logger.addHandler(handler)
    logger.propagate = True
    return logger


def get_api() -> FastAPI:
    """FastAPI 앱 인스턴스 반환"""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """서버 시작/종료 시 실행되는 lifespan 이벤트"""
        # 서버 시작 시
        logger = logging.getLogger("lexguard-mcp")
        logger.info("🚀 LexGuard MCP 서버 시작")
        yield
        # 서버 종료 시
        logger.info("🛑 LexGuard MCP 서버 종료 중...")
    
    api = FastAPI(
        title="LexGuard API Tools",
        description="한국 법령 및 행정규칙을 검색하고 상세 내용을 조회하는 GPT Actions 친화형 API입니다.",
        version="1.2.0",
        lifespan=lifespan,
    )
    
    # CORS 설정 추가 (Cursor 등 클라이언트에서 접근 가능하도록)
    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 개발 환경에서는 모든 origin 허용
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    return api


def get_mcp() -> FastMCP:
    """FastMCP 인스턴스 반환"""
    return FastMCP[Any]()

