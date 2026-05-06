"""pytest 공용 부트스트랩.

여기서 app.db.registry 를 import 해서 모든 SQLAlchemy 모델을 메타데이터에
등록한다. User.relationship("Address", ...) 같은 string ref 는 mapper configure
시점(첫 인스턴스화/쿼리)에 resolve 되는데, 그 시점에 모든 모델 클래스가
메모리에 로드돼 있어야 한다 — 안 그러면 InvalidRequestError 가 난다.

이 파일은 pytest 가 테스트 수집 직전에 자동 import 하므로 (pytest 관례),
모든 테스트가 영향을 받는다 — 한 도메인만 테스트해도 전체 모델이 로드된다.
"""

from app.db import registry  # noqa: F401
