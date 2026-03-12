"""
HTTP Routes - 일반 HTTP 엔드포인트
Controller 패턴: 요청을 받아 Service를 호출
"""
from typing import Any, Dict
from fastapi import FastAPI, Request
from starlette.requests import ClientDisconnect
from ..services.law_service import LawService
from ..services.health_service import HealthService
from ..services.administrative_rule_service import AdministrativeRuleService
from ..models import (
    GPTActionSearchLawRequest,
    GPTActionListLawNamesRequest,
    GPTActionGetLawDetailRequest,
    GPTActionSearchAdminRuleRequest,
    GPTActionGetAdminRuleDetailRequest,
    GPTActionLawSearchResponse,
    GPTActionLawNameListResponse,
    GPTActionLawDetailResponse,
    GPTActionAdminRuleSearchResponse,
    GPTActionAdminRuleDetailResponse,
    GPTActionHealthResponse,
    SearchLawRequest,
    ListLawNamesRequest,
    GetLawDetailRequest,
    SearchAdministrativeRuleRequest,
    GetAdminRuleDetailRequest,
)
from contextlib import contextmanager
import os
import logging

logger = logging.getLogger("lexguard-mcp")


@contextmanager
def temporary_env(overrides: dict):
    """임시 환경 변수 설정 컨텍스트 매니저"""
    saved_values = {}
    try:
        for key, value in (overrides or {}).items():
            saved_values[key] = os.environ.get(key)
            if value is not None:
                os.environ[key] = str(value)
        yield
    finally:
        for key, original in saved_values.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original


def register_http_routes(api: FastAPI, law_service: LawService, health_service: HealthService):
    """HTTP 엔드포인트 등록"""
    admin_rule_service = AdministrativeRuleService()

    def _model_dump(model: Any) -> Dict[str, Any]:
        if hasattr(model, "model_dump"):
            return model.model_dump(exclude_none=True)
        return model.dict(exclude_none=True)

    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _build_action_response(result: dict, success_message: str, payload: dict) -> dict:
        is_error = "error" in result
        message = result.get("message")
        if not message:
            message = result.get("error") if is_error else success_message
        return {
            "status": "error" if is_error else "success",
            "message": message,
            "result": payload,
            "error": result.get("error"),
            "recovery_guide": result.get("recovery_guide"),
        }

    def _extract_law_name(item: dict) -> str | None:
        return (
            item.get("법령명한글")
            or item.get("lawNm")
            or item.get("법령명")
            or item.get("lawNmKo")
        )

    def _extract_law_id(item: dict) -> str | None:
        value = (
            item.get("법령ID")
            or item.get("lawId")
            or item.get("법령일련번호")
            or item.get("lawSeq")
            or item.get("일련번호")
            or item.get("id")
        )
        return str(value) if value is not None else None

    def _extract_rule_name(item: dict) -> str | None:
        return (
            item.get("admrulNm")
            or item.get("행정규칙명")
            or item.get("행정규칙명한글")
        )

    def _extract_rule_id(item: dict) -> str | None:
        value = (
            item.get("행정규칙ID")
            or item.get("admrulId")
            or item.get("행정규칙일련번호")
            or item.get("admrulSeq")
            or item.get("id")
        )
        return str(value) if value is not None else None

    def _normalize_law_item(item: dict) -> dict:
        return {
            "name": _extract_law_name(item),
            "law_id": _extract_law_id(item),
            "law_serial_number": (
                item.get("법령일련번호")
                or item.get("lawSeq")
                or item.get("일련번호")
            ),
            "law_type": item.get("법령구분명") or item.get("lawClsNm"),
            "ministry": item.get("소관부처명") or item.get("deptName"),
            "effective_date": item.get("시행일자") or item.get("efYd"),
            "promulgation_date": item.get("공포일자") or item.get("promulgationDate"),
            "detail_link": item.get("법령상세링크") or item.get("detailLink"),
            "raw": item,
        }

    def _normalize_rule_item(item: dict) -> dict:
        return {
            "name": _extract_rule_name(item),
            "rule_id": _extract_rule_id(item),
            "rule_serial_number": (
                item.get("행정규칙일련번호")
                or item.get("admrulSeq")
            ),
            "rule_type": item.get("행정규칙종류") or item.get("admrulKnd"),
            "ministry": item.get("소관부처명") or item.get("orgNm"),
            "effective_date": item.get("시행일자") or item.get("efYd"),
            "promulgation_date": item.get("발령일자") or item.get("promulgationDate"),
            "detail_link": item.get("행정규칙상세링크") or item.get("detailLink"),
            "raw": item,
        }
    
    @api.get("/", include_in_schema=False)
    @api.head("/", include_in_schema=False)
    async def root():
        """루트 경로 - Render 포트 감지 및 서버 정보"""
        return {
            "service": "LexGuard MCP",
            "status": "running",
            "endpoints": {
                "health": "/health",
                "mcp": "/mcp",
                "tools": "/tools"
            },
            "message": "한국 법령 MCP 서버가 정상적으로 실행 중입니다."
        }
    
    @api.get(
        "/health",
        response_model=GPTActionHealthResponse,
        operation_id="getHealthStatus",
        summary="서버 상태 확인",
        description="API 서버 및 법령 검색 기능 사용 가능 여부를 확인합니다.",
    )
    async def health_check_get(request: Request):
        """HTTP GET endpoint: Health check"""
        logger.info("=" * 80)
        logger.info(f"HEALTH GET REQUEST: Client={request.client}, Query={request.query_params}")
        logger.info(f"Headers: {dict(request.headers)}")
        result = await health_service.check_health()
        logger.info(f"Health Response: {result['status']}, Ready: {result['environment']['api_ready']}")
        logger.info("=" * 80)
        return result
    
    @api.post("/health", include_in_schema=False)
    async def health_check_post(request: Request):
        """HTTP POST endpoint: Health check"""
        logger.info("=" * 80)
        logger.info(f"HEALTH POST REQUEST: Client={request.client}, Query={request.query_params}")
        logger.info(f"Headers: {dict(request.headers)}")
        try:
            body = await request.json()
            logger.info(f"Body: {body}")
        except Exception:
            logger.info("Body: <Cannot parse JSON or empty>")
        result = await health_service.check_health()
        logger.info(f"Health Response: {result['status']}, Ready: {result['environment']['api_ready']}")
        logger.info("=" * 80)
        return result
    
    @api.get("/check-ip", include_in_schema=False)
    async def check_server_ip():
        """서버의 실제 발신 IP 확인 (법령정보센터 등록용)"""
        import requests
        try:
            # 외부 IP 확인 서비스 호출
            response = requests.get("https://api.ipify.org?format=json", timeout=5)
            external_ip = response.json().get("ip", "Unknown")
            return {
                "server_external_ip": external_ip,
                "message": "이 IP를 국가법령정보센터 API 설정에 등록하세요",
                "instruction": "OPEN API 신청 > 서버장비의 IP주소 필드에 추가"
            }
        except Exception as e:
            return {
                "error": str(e),
                "message": "IP 확인 실패"
            }
    
    @api.get("/tools", include_in_schema=False)
    async def get_tools_http():
        """HTTP endpoint: Get list of available tools"""
        try:
            tools_list = [
                {
                    "name": "health",
                    "description": "서비스 상태 확인 (API 키 설정 등)",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                {
                    "name": "search_law_tool",
                    "description": "법령을 검색합니다 (법령명 또는 키워드로 검색)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "법령 검색어"},
                            "page": {"type": "integer", "description": "페이지 번호 (기본값: 1)"},
                            "per_page": {"type": "integer", "description": "페이지당 결과 수 (기본값: 10, 최대: 50)"}
                        },
                        "required": ["query"]
                    }
                },
                {
                    "name": "list_law_names_tool",
                    "description": "법령명 목록을 조회합니다 (전체 법령명 목록 또는 검색어로 필터링)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page": {"type": "integer", "description": "페이지 번호 (기본값: 1)"},
                            "per_page": {"type": "integer", "description": "페이지당 결과 수 (기본값: 50, 최대: 100)"},
                            "query": {"type": "string", "description": "검색어 (법령명으로 필터링, 선택사항)"}
                        },
                        "required": []
                    }
                },
                {
                    "name": "get_law_detail_tool",
                    "description": "법령 상세 정보를 조회합니다 (법령명으로 검색하여 상세 정보 조회)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "law_name": {"type": "string", "description": "법령명 (예: '119구조·구급에 관한 법률 시행령')"}
                        },
                        "required": ["law_name"]
                    }
                },
                {
                    "name": "search_admin_rule_tool",
                    "description": "행정규칙(훈령, 예규, 고시, 지침 등)을 검색합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "행정규칙 검색어"},
                            "page": {"type": "integer", "description": "페이지 번호 (기본값: 1)"},
                            "per_page": {"type": "integer", "description": "페이지당 결과 수 (기본값: 10, 최대: 100)"}
                        },
                        "required": ["query"]
                    }
                },
                {
                    "name": "get_admin_rule_detail_tool",
                    "description": "특정 행정규칙의 상세 정보를 조회합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "rule_name": {"type": "string", "description": "조회할 행정규칙의 이름 (예: '공무원 여비 규정')"}
                        },
                        "required": ["rule_name"]
                    }
                }
            ]
            
            return tools_list
        except Exception as e:
            logger.exception("Error getting tools list: %s", str(e))
            return []
    
    @api.post(
        "/tools/search_law_tool",
        response_model=GPTActionLawSearchResponse,
        operation_id="searchLawTool",
        summary="법령 검색",
        description="법령명 또는 키워드로 법령 후보를 검색합니다. 상세 조회 전에 먼저 이 액션을 사용합니다.",
    )
    async def search_law_tool_action(request_data: GPTActionSearchLawRequest):
        payload = _model_dump(request_data)
        req = SearchLawRequest(**payload)
        result = await law_service.search_law(req, arguments=payload)
        items = [_normalize_law_item(item) for item in result.get("laws", []) if isinstance(item, dict)]
        normalized = {
            "query": result.get("query", request_data.query),
            "items": items,
            "count": len(items),
            "total": _safe_int(result.get("total")),
            "page": result.get("page", request_data.page),
            "per_page": result.get("per_page", request_data.per_page),
            "api_url": result.get("api_url"),
        }
        return _build_action_response(result, "법령 검색 결과입니다.", normalized)

    @api.post(
        "/tools/list_law_names_tool",
        response_model=GPTActionLawNameListResponse,
        operation_id="listLawNamesTool",
        summary="법령명 목록 조회",
        description="전체 법령명 목록을 조회하거나 검색어로 필터링합니다.",
    )
    async def list_law_names_tool_action(request_data: GPTActionListLawNamesRequest):
        payload = _model_dump(request_data)
        req = ListLawNamesRequest(**payload)
        result = await law_service.list_law_names(req, arguments=payload)
        items = [{"name": name} for name in result.get("law_names", [])]
        normalized = {
            "query": result.get("query", request_data.query),
            "items": items,
            "count": len(items),
            "total": _safe_int(result.get("total")),
            "page": result.get("page", request_data.page),
            "per_page": result.get("per_page", request_data.per_page),
            "api_url": result.get("api_url"),
        }
        return _build_action_response(result, "법령명 목록 조회 결과입니다.", normalized)

    @api.post(
        "/tools/get_law_detail_tool",
        response_model=GPTActionLawDetailResponse,
        operation_id="getLawDetailTool",
        summary="법령 상세 조회",
        description="정확한 법령명으로 법령의 상세 내용을 조회합니다.",
    )
    async def get_law_detail_tool_action(request_data: GPTActionGetLawDetailRequest):
        payload = _model_dump(request_data)
        req = GetLawDetailRequest(**payload)
        result = await law_service.get_law_detail(req, arguments=payload)
        normalized = {
            "law_name": result.get("law_name", request_data.law_name),
            "law_id": result.get("law_id"),
            "detail": result.get("detail"),
            "articles": result.get("articles", []),
            "api_url": result.get("api_url"),
        }
        return _build_action_response(result, "법령 상세 조회 결과입니다.", normalized)

    @api.post(
        "/tools/search_admin_rule_tool",
        response_model=GPTActionAdminRuleSearchResponse,
        operation_id="searchAdminRuleTool",
        summary="행정규칙 검색",
        description="훈령, 예규, 고시, 지침 등 행정규칙을 검색합니다. 상세 조회 전에 먼저 이 액션을 사용합니다.",
    )
    async def search_admin_rule_tool_action(request_data: GPTActionSearchAdminRuleRequest):
        payload = _model_dump(request_data)
        req = SearchAdministrativeRuleRequest(**payload)
        result = await admin_rule_service.search_administrative_rule(req, arguments=payload)
        items = [_normalize_rule_item(item) for item in result.get("rules", []) if isinstance(item, dict)]
        normalized = {
            "query": result.get("query", request_data.query),
            "items": items,
            "count": len(items),
            "total": _safe_int(result.get("total")),
            "page": result.get("page", request_data.page),
            "per_page": result.get("per_page", request_data.per_page),
            "api_url": result.get("api_url"),
        }
        return _build_action_response(result, "행정규칙 검색 결과입니다.", normalized)

    @api.post(
        "/tools/get_admin_rule_detail_tool",
        response_model=GPTActionAdminRuleDetailResponse,
        operation_id="getAdminRuleDetailTool",
        summary="행정규칙 상세 조회",
        description="정확한 행정규칙명으로 상세 내용을 조회합니다.",
    )
    async def get_admin_rule_detail_tool_action(request_data: GPTActionGetAdminRuleDetailRequest):
        payload = _model_dump(request_data)
        req = GetAdminRuleDetailRequest(**payload)
        result = await admin_rule_service.get_administrative_rule_detail(req, arguments=payload)
        normalized = {
            "rule_name": result.get("rule_name", request_data.rule_name),
            "detail": result.get("detail"),
            "articles": result.get("articles", []),
            "api_url": result.get("api_url"),
        }
        return _build_action_response(result, "행정규칙 상세 조회 결과입니다.", normalized)

    @api.post("/tools/{tool_name}", include_in_schema=False)
    async def call_tool_http(tool_name: str, request_data: dict):
        """HTTP endpoint: Call tool"""
        try:
            logger.debug("HTTP call_tool | tool=%s request=%s", tool_name, request_data)
        except ClientDisconnect:
            logger.info("Client disconnected during tool call (normal for cancelled requests)")
            return {"error": "Client disconnected", "recovery_guide": "요청이 취소되었습니다."}
        
        env = request_data.get("env", {}) if isinstance(request_data, dict) else {}
        
        def convert_float_to_int(data: dict, keys: list):
            """Convert float values to int for specified keys"""
            for key in keys:
                if key in data and isinstance(data[key], float):
                    data[key] = int(data[key])
        
        try:
            creds = {}
            law_keys = ["LAW_API_KEY"]
            if isinstance(env, dict):
                for key in law_keys:
                    if key in env:
                        creds[key] = env[key]
            
            if creds:
                masked = dict(creds)
                for key in masked:
                    if masked[key]:
                        masked[key] = masked[key][:6] + "***"
                logger.debug("Applying temp env | %s", masked)
            
            async def run_with_env(coro_func):
                with temporary_env(creds):
                    return await coro_func
            
            if tool_name == "health":
                return await health_service.check_health()
            
            if tool_name == "search_law_tool":
                query = request_data.get("query")
                if not query:
                    return {
                        "error": "필수 파라미터 누락: query",
                        "recovery_guide": "검색어(query)를 입력해주세요."
                    }
                page = request_data.get("page", 1)
                per_page = request_data.get("per_page", 10)
                convert_float_to_int(request_data, ["page", "per_page"])
                req = SearchLawRequest(query=query, page=page, per_page=per_page)
                return await run_with_env(
                    law_service.search_law(req, arguments=request_data)
                )
            
            if tool_name == "list_law_names_tool":
                page = request_data.get("page", 1)
                per_page = request_data.get("per_page", 50)
                query = request_data.get("query")
                convert_float_to_int(request_data, ["page", "per_page"])
                req = ListLawNamesRequest(page=page, per_page=per_page, query=query)
                return await run_with_env(
                    law_service.list_law_names(req, arguments=request_data)
                )
            
            if tool_name == "get_law_detail_tool":
                law_name = request_data.get("law_name")
                if not law_name:
                    return {
                        "error": "필수 파라미터 누락: law_name",
                        "recovery_guide": "법령명(law_name)을 입력해주세요. 예: '형법', '민법', '개인정보보호법'"
                    }
                req = GetLawDetailRequest(law_name=law_name)
                return await run_with_env(
                    law_service.get_law_detail(req, arguments=request_data)
                )

            if tool_name == "search_admin_rule_tool":
                query = request_data.get("query")
                if not query:
                    return {
                        "error": "필수 파라미터 누락: query",
                        "recovery_guide": "행정규칙 검색어(query)를 입력해주세요."
                    }
                page = request_data.get("page", 1)
                per_page = request_data.get("per_page", 10)
                convert_float_to_int(request_data, ["page", "per_page"])
                from ..models import SearchAdministrativeRuleRequest
                from ..services.administrative_rule_service import AdministrativeRuleService
                req = SearchAdministrativeRuleRequest(query=query, page=page, per_page=per_page)
                admin_rule_service = AdministrativeRuleService()
                return await run_with_env(
                    admin_rule_service.search_administrative_rule(req, arguments=request_data)
                )

            if tool_name == "get_admin_rule_detail_tool":
                rule_name = request_data.get("rule_name")
                if not rule_name:
                    return {
                        "error": "필수 파라미터 누락: rule_name",
                        "recovery_guide": "행정규칙명(rule_name)을 입력해주세요. 예: '공무원 여비 규정'"
                    }
                from ..models import GetAdminRuleDetailRequest
                from ..services.administrative_rule_service import AdministrativeRuleService
                req = GetAdminRuleDetailRequest(rule_name=rule_name)
                admin_rule_service = AdministrativeRuleService()
                return await run_with_env(
                    admin_rule_service.get_administrative_rule_detail(req, arguments=request_data)
                )

            return {
                "error": "도구를 찾을 수 없습니다",
                "recovery_guide": "요청한 도구가 존재하지 않습니다. 사용 가능한 도구 목록을 확인하세요."
            }
        except Exception as e:
            logger.exception("Error in call_tool_http: %s", str(e))
            return {
                "error": f"도구 호출 중 오류 발생: {str(e)}",
                "recovery_guide": "시스템 오류가 발생했습니다. 서버 로그를 확인하거나 관리자에게 문의하세요."
            }

