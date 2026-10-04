"""eBay OAuth scope 목록 (모듈 1).

eBay scope는 전체 URL 형태이다: https://api.ebay.com/oauth/api_scope/...
full scope(e.g. sell.inventory)는 해당 영역의 읽기+쓰기를 모두 포함한다.
readonly 변형은 읽기 전용이 필요할 때 사용한다.

참고: https://developer.ebay.com/api-docs/static/oauth-scopes.html
"""

# 기본 scope: 대부분의 sell API 호출에 함께 요청
API_SCOPE = "https://api.ebay.com/oauth/api_scope"

# ---- 모듈 2: listing (Sell Inventory API) ----
SELL_INVENTORY = "https://api.ebay.com/oauth/api_scope/sell.inventory"
SELL_INVENTORY_READONLY = "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly"

# ---- 모듈 3: monitor - 주문 감시 (Sell Fulfillment API) ----
SELL_FULFILLMENT = "https://api.ebay.com/oauth/api_scope/sell.fulfillment"
SELL_FULFILLMENT_READONLY = "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly"

# ---- 모듈 3: monitor - 오퍼 감시 (Sell Negotiation API) ----
SELL_NEGOTIATION = "https://api.ebay.com/oauth/api_scope/sell.negotiation"
SELL_NEGOTIATION_READONLY = "https://api.ebay.com/oauth/api_scope/sell.negotiation.readonly"

# ---- 모듈 3: monitor - 셀러 계정 정보 (Sell Account API) ----
SELL_ACCOUNT = "https://api.ebay.com/oauth/api_scope/sell.account"
SELL_ACCOUNT_READONLY = "https://api.ebay.com/oauth/api_scope/sell.account.readonly"

# 기본 동의 scope: 이 프로젝트 전체 모듈이 필요로 하는 scope 모음.
# full scope가 읽기 권한도 포함하므로 readonly는 따로 요청하지 않는다.
DEFAULT_SCOPES = [
    API_SCOPE,
    SELL_INVENTORY,
    SELL_FULFILLMENT,
    SELL_ACCOUNT,
]
# 참고: SELL_NEGOTIATION은 Production 키셋에 미부여 (eBay 셀프서비스 추가 불가).
# Best Offer 감시는 기존 브라우저 방식으로 유지.

# 모듈별 필요 scope 정리표 (README/docs용)
SCOPES_BY_MODULE = {
    "listing (리스팅 대량 등록)": [API_SCOPE, SELL_INVENTORY],
    "monitor (주문 감시)": [API_SCOPE, SELL_FULFILLMENT, SELL_ACCOUNT],
    "monitor (오퍼 감시)": [API_SCOPE, SELL_NEGOTIATION],
    "sku (SKU 일괄 업데이트)": [API_SCOPE, SELL_INVENTORY],
}
