import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services.mobile_auth_service import MobileAuthService


def test_mobile_login_flow_emits_tokens_once():
    async def scenario():
        service = MobileAuthService()

        request = await service.create_request(
            username="admin",
            device_name="Pixel 8",
            request_ip="10.0.0.5",
        )

        pending = await service.list_pending()
        assert [item.request_id for item in pending] == [request.request_id]

        approved = await service.approve(request_id=request.request_id, actor="desktop-admin")
        assert approved.status == "APPROVED"
        assert approved.approved_at is not None

        snapshot, access_token, refresh_token = await service.consume_tokens_if_approved(
            request_id=request.request_id,
            request_token=request.request_token,
        )
        assert snapshot.status == "COMPLETED"
        assert snapshot.completed_at is not None
        assert access_token
        assert refresh_token

        _, access_token_again, refresh_token_again = await service.consume_tokens_if_approved(
            request_id=request.request_id,
            request_token=request.request_token,
        )
        assert access_token_again is None
        assert refresh_token_again is None

    asyncio.run(scenario())


def test_mobile_request_reject_and_cancel_paths():
    async def scenario():
        service = MobileAuthService()

        pending = []
        for idx in range(2):
            record = await service.create_request(
                username=f"user{idx}",
                device_name=f"Device-{idx}",
                request_ip=f"192.168.0.{idx+1}",
            )
            pending.append(record)

        rejected = await service.reject(request_id=pending[0].request_id, actor="desktop-admin")
        assert rejected.status == "REJECTED"
        assert rejected.approved_by == "desktop-admin"

        canceled = await service.cancel(
            request_id=pending[1].request_id,
            request_token=pending[1].request_token,
            actor="requester",
        )
        assert canceled.status == "CANCELED"
        assert canceled.approved_by == "requester"

        status = await service.get_status(
            request_id=pending[0].request_id,
            request_token=pending[0].request_token,
        )
        assert status.status == "REJECTED"

        snapshot, access_token, refresh_token = await service.consume_tokens_if_approved(
            request_id=pending[0].request_id,
            request_token=pending[0].request_token,
        )
        assert snapshot.status == "REJECTED"
        assert access_token is None
        assert refresh_token is None

    asyncio.run(scenario())


def test_expired_requests_are_cleaned_up():
    async def scenario():
        service = MobileAuthService()
        record = await service.create_request(
            username="admin",
            device_name="Old Phone",
            request_ip="127.0.0.1",
        )

        stored = service._requests[record.request_id]
        stored.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

        pending = await service.list_pending()
        assert pending == []

        with pytest.raises(KeyError):
            await service.get_status(request_id=record.request_id, request_token=record.request_token)

    asyncio.run(scenario())


def test_mobile_request_token_is_required_for_poll_and_cancel():
    async def scenario():
        service = MobileAuthService()
        record = await service.create_request(
            username="admin",
            device_name="Phone",
            request_ip="127.0.0.1",
        )

        with pytest.raises(PermissionError):
            await service.get_status(request_id=record.request_id, request_token="wrong-token")

        with pytest.raises(PermissionError):
            await service.cancel(
                request_id=record.request_id,
                request_token="wrong-token",
                actor="requester",
            )

    asyncio.run(scenario())
