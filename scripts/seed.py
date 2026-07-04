"""개발용 더미 데이터 삽입 스크립트.

실행:
    .venv/bin/python scripts/seed.py

재실행 안전: 이미 존재하는 이메일은 건너뜁니다.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload

import app.db.registry  # noqa: F401 — 모든 모델을 SQLAlchemy 메타데이터에 등록
from app.core.config import settings
from app.core.security import hash_password
from app.catalog.models import ConditionGrade, Product, ProductCategoryMetaItem, ProductImage, ProductStatus
from app.cart.models import CartItem
from app.favorites.models import Favorite
from app.help.models import Faq
from app.user.models import User, UserRole
from app.address.models import Address


# ── 엔진 ──────────────────────────────────────────────────────────────────────

engine = create_async_engine(settings.database_url, echo=False)


async def get_or_create_user(
    session: AsyncSession,
    *,
    login_id: str,
    email: str,
    username: str,
    role: UserRole = UserRole.USER,
    password: str = "Test1234!",
) -> User:
    result = await session.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()
    if existing:
        print(f"  [skip] 유저 이미 존재: {email}")
        return existing
    now = datetime.now(UTC)
    user = User(
        login_id=login_id,
        email=email,
        password_hash=hash_password(password),
        username=username,
        role=role,
        is_active=True,
        agreed_terms_at=now,
        agreed_privacy_at=now,
        identity_verified_at=now,  # 주문 테스트용
        phone="01012345678",
        phone_verified_at=now,
    )
    session.add(user)
    await session.flush()
    print(f"  [ok]   유저 생성: {email}  (id={user.id})")
    return user


async def seed_products(session: AsyncSession) -> list[Product]:
    result = await session.execute(select(Product).limit(1))
    if result.scalar_one_or_none():
        print("  [skip] 상품 이미 존재 — 기존 상품 반환")
        rows = await session.execute(
            select(Product)
            .options(selectinload(Product.images))
            .limit(10)
        )
        return list(rows.scalars().all())

    products_data = [
        dict(
            title="LG 냉장고 462L 실버 2019년식",
            description="성능 이상 없음. 외관 흠집 약간 있으나 작동 완벽. 직배송 가능.",
            category="REFRIGERATOR",
            brand="LG전자",
            model_name="DIOS J555SB35",
            year_estimate=2019,
            condition_grade=ConditionGrade.A,
            warranty_works=True,
            price=380_000,
            original_price=1_200_000,
            weight_kg=86.0,
            width_cm=70,
            depth_cm=77,
            height_cm=180,
            stock=1,
            status=ProductStatus.ACTIVE,
            images=[
                "https://images.unsplash.com/photo-1571175443880-49e1d25b2bc5?w=600",
                "https://images.unsplash.com/photo-1584568694244-14fbdf83bd30?w=600",
            ],
        ),
        dict(
            title="삼성 드럼세탁기 12kg 화이트",
            description="2021년 구매, 이사로 처분. 찌그러짐 없음. 포장 후 배송 가능.",
            category="WASHING_MACHINE",
            brand="삼성전자",
            model_name="WF12T8000KW",
            year_estimate=2021,
            condition_grade=ConditionGrade.B,
            warranty_works=True,
            price=450_000,
            original_price=1_500_000,
            weight_kg=73.0,
            width_cm=60,
            depth_cm=60,
            height_cm=85,
            stock=1,
            status=ProductStatus.ACTIVE,
            images=[
                "https://images.unsplash.com/photo-1626806787461-102c1bfaaea1?w=600",
                "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=600",
            ],
        ),
        dict(
            title="LG 올레드 TV 65인치 2020년",
            description="패널 완벽. 리모콘·스탠드 포함. 직거래만 가능 (서울 강남).",
            category="TV",
            brand="LG전자",
            model_name="OLED65C9PUA",
            year_estimate=2020,
            condition_grade=ConditionGrade.A,
            warranty_works=True,
            price=950_000,
            original_price=3_200_000,
            stock=1,
            status=ProductStatus.ACTIVE,
            images=[
                "https://images.unsplash.com/photo-1593359677879-a4bb92f829d1?w=600",
            ],
        ),
        dict(
            title="캐리어 에어컨 18평 스탠드형",
            description="2018년 설치. 냉방 잘 됨. 실외기 함께 판매.",
            category="AIR_CONDITIONER",
            brand="캐리어",
            model_name="CSV-Q185KX",
            year_estimate=2018,
            condition_grade=ConditionGrade.B,
            warranty_works=True,
            price=280_000,
            original_price=900_000,
            stock=1,
            status=ProductStatus.ACTIVE,
            images=[
                "https://images.unsplash.com/photo-1585771724684-38269d6639fd?w=600",
            ],
        ),
        dict(
            title="삼성 김치냉장고 234L",
            description="도어 실링 교체 완료. 냉각 정상 작동. 택배 불가, 직배만.",
            category="REFRIGERATOR",
            brand="삼성전자",
            model_name="RP22R31513H",
            year_estimate=2017,
            condition_grade=ConditionGrade.C,
            warranty_works=True,
            price=120_000,
            original_price=680_000,
            stock=1,
            status=ProductStatus.ACTIVE,
            images=[
                "https://images.unsplash.com/photo-1584568694244-14fbdf83bd30?w=600",
            ],
        ),
        dict(
            title="다이슨 V11 청소기 (부품 일부 분실)",
            description="흡입력 정상. 배터리 수명 약 20분. 부품 없이 판매.",
            category="ETC",
            brand="다이슨",
            model_name="V11 Fluffy",
            year_estimate=2022,
            condition_grade=ConditionGrade.B,
            warranty_works=True,
            price=250_000,
            original_price=800_000,
            stock=2,
            status=ProductStatus.ACTIVE,
            images=[
                "https://images.unsplash.com/photo-1558317374-067fb5f30001?w=600",
            ],
        ),
    ]

    created: list[Product] = []
    for d in products_data:
        image_urls: list[str] = d.pop("images")  # type: ignore[assignment]
        product = Product(**d)
        for i, url in enumerate(image_urls):
            product.images.append(ProductImage(url=url, sort_order=i))
        session.add(product)
        await session.flush()
        print(f"  [ok]   상품 생성: {product.title[:30]}  (id={product.id})")
        created.append(product)
    return created


async def seed_categories(session: AsyncSession) -> None:
    CATEGORIES = [
        dict(id="REFRIGERATOR", title="냉장고", icon="fridge", sort_order=1),
        dict(id="WASHING_MACHINE", title="세탁기", icon="washer", sort_order=2),
        dict(id="TV", title="TV", icon="tv", sort_order=3),
        dict(id="AIR_CONDITIONER", title="에어컨", icon="aircon", sort_order=4),
        dict(id="KITCHEN", title="주방가전", icon="microwave", sort_order=5),
        dict(id="ETC", title="기타", icon="menu", sort_order=99),
    ]
    for data in CATEGORIES:
        existing = await session.execute(
            select(ProductCategoryMetaItem).where(ProductCategoryMetaItem.id == data["id"])
        )
        if existing.scalar_one_or_none():
            print(f"  [skip] 카테고리 이미 존재: {data['id']}")
            continue
        session.add(ProductCategoryMetaItem(**data))
        print(f"  [ok]   카테고리 생성: {data['id']}")
    await session.flush()


async def seed_faqs(session: AsyncSession) -> None:
    # category -> [(question, answer), ...] — sort_order 는 카테고리 내 순서로 자동 부여
    faqs_by_category: dict[str, list[tuple[str, str]]] = {
        "주문": [
            ("주문한 상품은 취소할 수 있나요?",
             "결제 완료 후 배송 시작 전까지는 마이페이지 > 주문내역에서 직접 취소할 수 있습니다. "
             "이미 배송이 시작된 경우에는 판매자와 협의 후 반품 절차를 이용해 주세요."),
            ("여러 판매자의 상품을 한 번에 주문할 수 있나요?",
             "장바구니에 담아 한 번에 결제하실 수 있지만, 판매자가 다른 상품은 각각 별도 배송으로 "
             "처리되며 배송비도 판매자 단위로 계산됩니다."),
            ("주문 상태는 어디서 확인하나요?",
             "마이페이지 > 주문내역에서 결제완료, 배송준비중, 배송중, 배송완료 단계를 실시간으로 "
             "확인할 수 있습니다."),
        ],
        "배송": [
            ("배송비는 어떻게 계산되나요?",
             "상품의 무게, 크기, 배송지까지의 거리를 기준으로 자동 계산됩니다. 결제 전 견적 화면에서 "
             "정확한 배송비를 미리 확인할 수 있습니다."),
            ("냉장고나 세탁기 같은 대형 가전은 어떻게 배송되나요?",
             "소형 가전은 일반 택배(파렛트), 대형 가전은 화물 택배로 배송됩니다. 서울/경기 지역은 "
             "철거 차량을 이용한 직접 배송도 가능합니다."),
            ("배송 조회는 어떻게 하나요?",
             "주문내역 상세 화면에서 배송 상태를 확인할 수 있으며, 송장번호가 등록되면 배송 조회 "
             "링크로 실시간 위치 추적도 가능합니다."),
        ],
        "결제": [
            ("어떤 결제 수단을 지원하나요?",
             "신용/체크카드, 실시간 계좌이체, 카카오페이·네이버페이 등 간편결제를 지원합니다."),
            ("환불은 얼마나 걸리나요?",
             "판매자 확인 및 반품 상품 검수가 끝나면 영업일 기준 3~5일 내 결제하신 수단으로 "
             "환불 처리됩니다."),
            ("현금영수증이나 세금계산서 발행이 가능한가요?",
             "마이페이지 > 주문내역에서 결제 건별로 현금영수증 발급을 요청할 수 있습니다. "
             "세금계산서는 1:1 문의를 통해 접수해 주세요."),
        ],
        "회원": [
            ("비회원도 구매할 수 있나요?",
             "아니요. rekit은 안전한 직거래를 위해 회원가입 후 구매/판매가 가능합니다."),
            ("비밀번호를 잊어버렸어요.",
             "로그인 화면의 '비밀번호 찾기'에서 가입 시 등록한 이메일로 재설정 링크를 받을 수 "
             "있습니다."),
            ("회원 탈퇴는 어떻게 하나요?",
             "마이페이지 > 계정 설정 > 회원 탈퇴에서 진행할 수 있습니다. 진행 중인 주문이나 "
             "미완료 정산이 있으면 탈퇴가 제한됩니다."),
        ],
        "상품": [
            ("상품의 상태 등급(A/B/C)은 무슨 기준인가요?",
             "A는 사용감이 거의 없는 상태, B는 사용감이 있지만 정상 작동, C는 흠집이 많지만 "
             "작동에는 문제없는 상태를 의미합니다. 등급별 실제 사진이 상품 상세페이지에 함께 "
             "표시됩니다."),
            ("관심 상품은 어디서 모아볼 수 있나요?",
             "상품 상세페이지의 하트 아이콘을 누르면 마이페이지 > 관심상품 목록에서 모아볼 수 "
             "있습니다."),
        ],
        "기타": [
            ("문의는 어떻게 남기나요?",
             "로그인 후 고객센터 > 1:1 문의에서 남겨주시면 영업일 기준 1~2일 내 답변드립니다. "
             "답변이 등록되면 가입하신 이메일로도 안내드립니다."),
            ("고객센터 운영시간은 어떻게 되나요?",
             "평일 09:00~18:00 운영하며 주말/공휴일은 휴무입니다. 운영시간 외 문의는 다음 "
             "영업일에 순차적으로 답변드립니다."),
        ],
    }

    existing = set((await session.execute(select(Faq.category, Faq.question))).all())

    for category, items in faqs_by_category.items():
        for sort_order, (question, answer) in enumerate(items, start=1):
            if (category, question) in existing:
                print(f"  [skip] FAQ 이미 존재: [{category}] {question[:20]}")
                continue
            session.add(
                Faq(category=category, question=question, answer=answer, sort_order=sort_order)
            )
            print(f"  [ok]   FAQ 생성: [{category}] {question[:20]}")
    await session.flush()


async def seed_address(session: AsyncSession, user: User) -> Address:
    result = await session.execute(
        select(Address).where(Address.user_id == user.id).limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing:
        print(f"  [skip] 배송지 이미 존재: user_id={user.id}")
        return existing
    addr = Address(
        user_id=user.id,
        recipient=user.username,
        phone="01012345678",
        zipcode="06236",
        address1="서울특별시 강남구 테헤란로 123",
        address2="101동 202호",
        is_default=True,
    )
    session.add(addr)
    await session.flush()
    print(f"  [ok]   배송지 생성: {addr.address1}")
    return addr


async def seed_cart(
    session: AsyncSession, user: User, products: list[Product]
) -> None:
    for product in products[:2]:
        result = await session.execute(
            select(CartItem).where(
                CartItem.user_id == user.id,
                CartItem.product_id == product.id,
            )
        )
        if result.scalar_one_or_none():
            print(f"  [skip] 장바구니 이미 존재: product_id={product.id}")
            continue
        item = CartItem(user_id=user.id, product_id=product.id, quantity=1)
        session.add(item)
        print(f"  [ok]   장바구니 추가: {product.title[:30]}")
    await session.flush()


async def seed_favorites(
    session: AsyncSession, user: User, products: list[Product]
) -> None:
    for product in products[1:4]:
        result = await session.execute(
            select(Favorite).where(
                Favorite.user_id == user.id,
                Favorite.product_id == product.id,
            )
        )
        if result.scalar_one_or_none():
            print(f"  [skip] 관심상품 이미 존재: product_id={product.id}")
            continue
        fav = Favorite(user_id=user.id, product_id=product.id)
        session.add(fav)
        print(f"  [ok]   관심상품 추가: {product.title[:30]}")
    await session.flush()


async def main() -> None:
    print("=== 시드 데이터 삽입 시작 ===\n")

    async with AsyncSession(engine) as session:
        async with session.begin():

            print("[1] 유저 생성")
            admin = await get_or_create_user(
                session,
                login_id="admin01",
                email="admin@rekle.kr",
                username="관리자",
                role=UserRole.ADMIN,
                password="Admin1234!",
            )
            user = await get_or_create_user(
                session,
                login_id="hong001",
                email="user@rekle.kr",
                username="홍길동",
                role=UserRole.USER,
                password="User1234!",
            )
            user2 = await get_or_create_user(
                session,
                login_id="kim001",
                email="user2@rekle.kr",
                username="김철수",
                role=UserRole.USER,
                password="User1234!",
            )

            print("\n[2] 카테고리 생성")
            await seed_categories(session)

            print("\n[3] 상품 생성")
            products = await seed_products(session)

            print("\n[4] 배송지 생성")
            await seed_address(session, user)
            await seed_address(session, user2)

            print("\n[5] 장바구니 추가")
            await seed_cart(session, user, products)

            print("\n[6] 관심상품 추가")
            await seed_favorites(session, user, products)

            print("\n[7] FAQ 생성")
            await seed_faqs(session)

    await engine.dispose()

    print("\n=== 완료 ===")
    print("\n계정 정보:")
    print("  관리자  login_id=admin01  email=admin@rekle.kr  / Admin1234!")
    print("  유저1   login_id=hong001  email=user@rekle.kr   / User1234!")
    print("  유저2   login_id=kim001   email=user2@rekle.kr  / User1234!")


if __name__ == "__main__":
    asyncio.run(main())
