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


def test_pending_risk_summary_for_new_public_ip_is_high():
    async def scenario():
        service = MobileAuthService()
        record = await service.create_request(
            username="admin",
            device_name="Traveler Phone",
            request_ip="8.8.8.8",
        )

        pending = await service.list_pending_with_risk()
        assert len(pending) == 1
        snapshot, risk = pending[0]
        assert snapshot.request_id == record.request_id
        assert risk.risk_level == "HIGH"
        assert risk.ip_risk_level == "HIGH"
        assert set(risk.risk_reasons) == {"NEW_DEVICE", "NEW_IP", "PUBLIC_SOURCE_IP"}
        assert risk.known_device is False
        assert risk.known_ip is False
        assert risk.device_approval_count == 0
        assert risk.ip_seen_count == 0

    asyncio.run(scenario())


def test_pending_risk_summary_for_known_device_and_ip_is_low():
    async def scenario():
        service = MobileAuthService()
        first = await service.create_request(
            username="admin",
            device_name="Pixel 9",
            request_ip="192.168.10.15",
        )
        await service.approve(request_id=first.request_id, actor="desktop-admin")

        second = await service.create_request(
            username="admin",
            device_name="Pixel 9",
            request_ip="192.168.10.15",
        )
        pending = await service.list_pending_with_risk()
        assert len(pending) == 1
        snapshot, risk = pending[0]
        assert snapshot.request_id == second.request_id
        assert risk.risk_level == "LOW"
        assert risk.ip_risk_level == "LOW"
        assert risk.risk_reasons == []
        assert risk.known_device is True
        assert risk.known_ip is True
        assert risk.device_approval_count == 1
        assert risk.ip_seen_count == 1
        assert risk.device_last_approved_at is not None
        assert risk.ip_last_seen_at is not None

    asyncio.run(scenario())


def test_pending_risk_summary_for_new_private_ip_is_medium():
    async def scenario():
        service = MobileAuthService()
        first = await service.create_request(
            username="admin",
            device_name="Pixel 9",
            request_ip="192.168.10.15",
        )
        await service.approve(request_id=first.request_id, actor="desktop-admin")

        second = await service.create_request(
            username="admin",
            device_name="Pixel 9",
            request_ip="192.168.10.24",
        )
        pending = await service.list_pending_with_risk()
        assert len(pending) == 1
        snapshot, risk = pending[0]
        assert snapshot.request_id == second.request_id
        assert risk.risk_level == "MEDIUM"
        assert risk.ip_risk_level == "LOW"
        assert risk.risk_reasons == ["NEW_IP"]
        assert risk.known_device is True
        assert risk.known_ip is False

    asyncio.run(scenario())


def test_history_cleanup_expires_stale_device_and_ip_records():
    async def scenario():
        service = MobileAuthService()
        first = await service.create_request(
            username="admin",
            device_name="iPhone 17",
            request_ip="192.168.50.22",
        )
        await service.approve(request_id=first.request_id, actor="desktop-admin")

        device_key = service._device_key(first)
        ip_key = service._ip_key(first)
        stale_time = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        service._device_histories[device_key].last_approved_at = stale_time
        service._ip_histories[ip_key].last_seen_at = stale_time

        second = await service.create_request(
            username="admin",
            device_name="iPhone 17",
            request_ip="192.168.50.22",
        )
        pending = await service.list_pending_with_risk()
        assert len(pending) == 1
        snapshot, risk = pending[0]
        assert snapshot.request_id == second.request_id
        assert risk.known_device is False
        assert risk.known_ip is False
        assert risk.risk_level == "MEDIUM"
        assert set(risk.risk_reasons) == {"NEW_DEVICE", "NEW_IP"}

    asyncio.run(scenario())


def test_ip_key_normalization_treats_ipv4_and_mapped_ipv6_as_same_source():
    async def scenario():
        service = MobileAuthService()
        first = await service.create_request(
            username="admin",
            device_name="Work Phone",
            request_ip="::ffff:192.168.60.88",
        )
        await service.approve(request_id=first.request_id, actor="desktop-admin")

        second = await service.create_request(
            username="admin",
            device_name="Work Phone",
            request_ip="192.168.60.88",
        )
        pending = await service.list_pending_with_risk()
        assert len(pending) == 1
        snapshot, risk = pending[0]
        assert snapshot.request_id == second.request_id
        assert risk.known_ip is True
        assert risk.risk_reasons == []
        assert risk.risk_level == "LOW"

    asyncio.run(scenario())


def test_non_global_source_ip_is_medium_risk():
    async def scenario():
        service = MobileAuthService()
        request = await service.create_request(
            username="admin",
            device_name="Carrier NAT Device",
            request_ip="100.64.1.9",
        )
        pending = await service.list_pending_with_risk()
        assert len(pending) == 1
        snapshot, risk = pending[0]
        assert snapshot.request_id == request.request_id
        assert risk.ip_risk_level == "MEDIUM"
        assert risk.risk_level == "MEDIUM"
        assert "NON_GLOBAL_SOURCE_IP" in risk.risk_reasons

    asyncio.run(scenario())
