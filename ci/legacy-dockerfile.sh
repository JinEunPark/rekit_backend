#!/bin/sh
# Generate the missing test/runtime stages for release tags 0.0.1 through 0.0.7.
# Run in the release checkout, passing the current CI Dockerfile as the argument.
set -eu
gate=$1

# These releases use the shared sync/async ping annotation in redis-py 7.4. Use the
# compatible client in both stages so the image we ship matches the tests.
sed 's/pip install -e \.$/pip install -e . redis==7.4.0/' Dockerfile

# These tests require external PostgreSQL or Redis and predate the infra marker.
set -- \
    tests/test_database_timeouts.py::test_engine_connection_applies_statement_timeout \
    tests/test_database_timeouts.py::test_engine_connection_applies_idle_in_transaction_timeout \
    tests/test_health.py::test_ready_returns_200_when_real_database_and_redis_respond \
    tests/test_metrics.py::test_db_pool_gauge_tracks_checkout_and_checkin \
    tests/test_metrics.py::test_app_engine_pool_stays_instrumented_after_dispose \
    tests/test_metrics.py::test_db_pool_checkout_wait_observed_per_connect \
    tests/test_metrics.py::test_db_pool_timeout_counted_when_pool_exhausted \
    tests/test_metrics.py::test_app_engine_pool_observes_checkout_wait_after_dispose
opts=
for node do
    opts="$opts --deselect=$node"
done


# The legacy router fixtures also start the S3 lifespan on entry to TestClient.
opts="$opts --ignore=tests/test_social_router_integration.py --ignore=tests/test_withdrawal_router_integration.py"
awk -v opts="$opts" '
    /^FROM base AS runtime$/ { exit }
    /^FROM base AS test$/ { active = 1; print; print "ENV PYTEST_ADDOPTS=\"" opts "\""; next }
    active { print }
' "$gate"
# The release base already defines EXPOSE and its release-specific CMD.
printf '\nFROM base AS runtime\n'
