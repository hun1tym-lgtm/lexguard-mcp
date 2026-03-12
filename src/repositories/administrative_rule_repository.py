"""
Administrative Rule Repository - 행정규칙 검색 기능
"""
import requests
import json
from typing import Optional
from .base import BaseLawRepository, logger, LAW_API_SEARCH_URL, search_cache, failure_cache


class AdministrativeRuleRepository(BaseLawRepository):
    """행정규칙 검색 관련 기능을 담당하는 Repository"""
    
    def search_administrative_rule(
        self,
        query: Optional[str] = None,
        agency: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        arguments: Optional[dict] = None
    ) -> dict:
        """행정규칙을 검색합니다."""
        logger.debug("search_administrative_rule called | query=%r agency=%r page=%d per_page=%d", 
                    query, agency, page, per_page)
        
        if per_page < 1:
            per_page = 1
        if per_page > 100:
            per_page = 100
        
        cache_key = ("administrative_rule", query or "", agency or "", page, per_page)
        
        if cache_key in search_cache:
            return search_cache[cache_key]
        if cache_key in failure_cache:
            return failure_cache[cache_key]
        
        try:
            params = {
                "target": "admrul",
                "type": "JSON",
                "page": page,
                "display": per_page
            }
            
            if query:
                params["query"] = self.normalize_search_query(query)
            
            if agency:
                # 부처명을 기관코드로 변환 (간단한 매핑)
                agency_code_map = {
                    "고용노동부": "100000",
                    "교육부": "200000",
                    "기획재정부": "300000",
                    # 필요시 더 추가
                }
                if agency in agency_code_map:
                    params["orgCd"] = agency_code_map[agency]
            
            _, api_key_error = self.attach_api_key(params, arguments, LAW_API_SEARCH_URL)
            if api_key_error:
                return api_key_error
            
            response = requests.get(LAW_API_SEARCH_URL, params=params, timeout=10)
            
            invalid_response = self.validate_drf_response(response)
            if invalid_response:
                return invalid_response
            response.raise_for_status()
            
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                return {
                    "error": f"API 응답이 유효한 JSON 형식이 아닙니다: {str(e)}",
                    "query": query,
                    "agency": agency,
                    "api_url": response.url,
                    "recovery_guide": "API 응답 형식 오류입니다. API 서버 상태를 확인하거나 잠시 후 다시 시도하세요."
                }
            
            result = {
                "query": query,
                "agency": agency,
                "page": page,
                "per_page": per_page,
                "total": 0,
                "rules": [],
                "api_url": response.url
            }
            
            if isinstance(data, dict):
                # API 응답 키가 AdmRulSearch(대문자 R) 또는 AdmrulSearch 로 올 수 있음
                search_key = "AdmRulSearch" if "AdmRulSearch" in data else "AdmrulSearch"
                if search_key in data:
                    admrul_search = data[search_key]
                    if isinstance(admrul_search, dict):
                        total_raw = admrul_search.get("totalCnt", 0)
                        try:
                            result["total"] = int(total_raw)
                        except (TypeError, ValueError):
                            result["total"] = 0
                        rules = admrul_search.get("admrul", [])
                    else:
                        rules = []
                elif "admrul" in data:
                    total_raw = data.get("totalCnt", 0)
                    try:
                        result["total"] = int(total_raw)
                    except (TypeError, ValueError):
                        result["total"] = 0
                    rules = data.get("admrul", [])
                else:
                    total_raw = data.get("totalCnt", 0)
                    try:
                        result["total"] = int(total_raw)
                    except (TypeError, ValueError):
                        result["total"] = 0
                    rules = data.get("admrul", [])
                
                if not isinstance(rules, list):
                    rules = [rules] if rules else []
                
                result["rules"] = rules[:per_page]
            
            # total은 있는데 목록이 비어 있는 경우 메타 정보 추가
            if result["total"] and not result["rules"]:
                result["note"] = "API 응답에서 totalCnt는 있으나 행정규칙 목록(admrul)이 비어 있습니다. 국가법령정보센터 응답 구조를 확인하세요."
            
            search_cache[cache_key] = result
            return result
            
        except requests.exceptions.Timeout:
            error_result = {
                "error": "API 호출 타임아웃",
                "recovery_guide": "네트워크 응답 시간이 초과되었습니다. 잠시 후 다시 시도하거나, 인터넷 연결을 확인하세요."
            }
            failure_cache[cache_key] = error_result
            return error_result
        except requests.exceptions.RequestException as e:
            error_result = {
                "error": f"API 요청 실패: {str(e)}",
                "recovery_guide": "네트워크 오류입니다. 잠시 후 다시 시도하거나, 인터넷 연결을 확인하세요."
            }
            failure_cache[cache_key] = error_result
            return error_result
            logger.exception("예상치 못한 오류")
            return {
                "error": f"예상치 못한 오류: {str(e)}",
                "recovery_guide": "시스템 오류가 발생했습니다. 서버 로그를 확인하거나 관리자에게 문의하세요."
            }
    
    def get_administrative_rule_detail(
        self,
        rule_name: str,
        arguments: Optional[dict] = None
    ) -> dict:
        """행정규칙의 상세 정보(조문 등)를 조회합니다."""
        logger.debug("get_administrative_rule_detail called | rule_name=%r", rule_name)
        
        # 행정규칙 조회도 동일하게 캐시 키 생성 (mode는 항상 detail)
        cache_key = ("admrul_detail", rule_name, "detail", None, None, None, None)
        
        if cache_key in search_cache:
            return search_cache[cache_key]
        if cache_key in failure_cache:
            return failure_cache[cache_key]
        
        # get_law와 달리 별도 API URL (LAW_API_BASE_URL)을 사용
        from .base import LAW_API_BASE_URL
        
        try:
            params = {
                "target": "admrul",
                "type": "JSON",
            }
            
            # rule_name이 숫자로만 이뤄진 일련번호가 아니라면, 검색 API를 통해 ID(행정규칙일련번호) 획득
            if not rule_name.isdigit():
                search_res = self.search_administrative_rule(query=rule_name, per_page=50, arguments=arguments)
                rules = search_res.get("rules", [])
                
                found_id = None
                norm_query = rule_name.replace(" ", "")
                for r in rules:
                    name = r.get("admrulNm", r.get("행정규칙명", ""))
                    if name.strip() == rule_name.strip():
                        found_id = r.get("admrulSeq", r.get("행정규칙일련번호"))
                        break
                
                if not found_id and rules:
                    for r in rules:
                        name = r.get("admrulNm", r.get("행정규칙명", ""))
                        if name.replace(" ", "") == norm_query:
                            found_id = r.get("admrulSeq", r.get("행정규칙일련번호"))
                            break
                            
                if not found_id and rules:
                    # 일치하는 이름이 없더라도 첫 번째 검색 결과를 제공하여 사용자 경험 유지
                    found_id = rules[0].get("admrulSeq", rules[0].get("행정규칙일련번호"))
                    
                if found_id:
                    params["ID"] = found_id
                else:
                    # 검색 결과조차 없으면 애초에 상세조회가 불가능하므로, 그냥 원래대로 query로 보냄
                    params["query"] = self.normalize_search_query(rule_name)
            else:
                params["ID"] = rule_name
            
            _, api_key_error = self.attach_api_key(params, arguments, LAW_API_BASE_URL)
            if api_key_error:
                return api_key_error
            
            response = requests.get(LAW_API_BASE_URL, params=params, timeout=10)
            
            invalid_response = self.validate_drf_response(response)
            if invalid_response:
                return invalid_response
                
            response.raise_for_status()
            
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                return {
                    "error": f"API 응답이 유효한 JSON 형식이 아닙니다: {str(e)}",
                    "rule_name": rule_name,
                    "api_url": response.url,
                    "recovery_guide": "API 응답 형식 오류입니다. API 서버 상태를 확인하거나 잠시 후 다시 시도하세요."
                }
                
            # 응답 데이터 파싱 로직 (원본 데이터 반환을 기본 구조로 잡습니다)
            result = {
                "rule_name": rule_name,
                "api_url": response.url,
                "detail": data
            }
            
            search_cache[cache_key] = result
            return result
            
        except requests.exceptions.Timeout:
            error_result = {
                "error": "API 호출 타임아웃",
                "recovery_guide": "네트워크 응답 시간이 초과되었습니다. 잠시 후 다시 시도하거나, 인터넷 연결을 확인하세요."
            }
            failure_cache[cache_key] = error_result
            return error_result
        except requests.exceptions.RequestException as e:
            error_result = {
                "error": f"API 요청 실패: {str(e)}",
                "recovery_guide": "네트워크 오류입니다. 잠시 후 다시 시도하거나, 인터넷 연결을 확인하세요."
            }
            failure_cache[cache_key] = error_result
            return error_result
        except Exception as e:
            logger.exception("예상치 못한 오류")
            return {
                "error": f"예상치 못한 오류: {str(e)}",
                "recovery_guide": "시스템 오류가 발생했습니다. 서버 로그를 확인하거나 관리자에게 문의하세요."
            }


