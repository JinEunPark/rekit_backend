"""배송비 / 할인 상수.

주문 견적(POST /orders/quote), 장바구니 배송비 안내, 서비스 로직에서 공통 사용.
"""

from app.order.shipment import ShipmentMethod

SHIPPING_FEE: dict[ShipmentMethod, int] = {
    ShipmentMethod.PARCEL: 5_000,
    ShipmentMethod.FREIGHT: 60_000,
    ShipmentMethod.DIRECT: 40_000,
}

DIRECT_DISCOUNT = 20_000
REFUND_WINDOW_DAYS = 7

# 직배송 가능 zipcode prefix (서울/경기 일부)
DIRECT_DELIVERY_PREFIXES = (
    "01", "02", "03", "04", "05", "06", "07", "08",  # 서울
    "10", "11", "12", "13", "14", "15", "16", "17", "18",  # 경기 일부
)


def is_direct_delivery_available(zipcode: str) -> bool:
    return zipcode[:2] in DIRECT_DELIVERY_PREFIXES


def calc_shipping(method: ShipmentMethod) -> tuple[int, int]:
    """(shipping_fee, discount_amount) 반환."""
    fee = SHIPPING_FEE[method]
    discount = DIRECT_DISCOUNT if method == ShipmentMethod.DIRECT else 0
    return fee, discount
