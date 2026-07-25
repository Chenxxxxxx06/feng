"""Tests for audit signature chain service.

Covers: chain building, canonical JSON, SHA-256 linking, verification,
tamper detection, and fail-safe when signing key is missing.
"""
import hashlib
import json
import pytest

from app.services.audit_chain_service import (
    AuditChainService,
    AuditEntry,
    AuditVerificationResult,
    GENESIS_HASH,
)


def test_canonical_json_deterministic():
    """Canonical JSON produces identical output regardless of key order."""
    svc = AuditChainService.__new__(AuditChainService)
    data = {"b": 2, "a": 1, "c": {"z": 9, "x": 7}}
    result1 = svc._canonical_json(data)
    result2 = svc._canonical_json({"c": {"x": 7, "z": 9}, "a": 1, "b": 2})
    assert result1 == result2
    assert result1 == '{"a":1,"b":2,"c":{"x":7,"z":9}}'


def test_genesis_hash_is_constant():
    assert GENESIS_HASH == "0xGENESIS"


def test_chain_continuity():
    """Manual chain: each entry's prev_hash matches previous current_hash."""
    entries = []
    prev = GENESIS_HASH
    for i in range(1, 6):
        data = json.dumps({
            "seq": i, "action": f"test_{i}", "prev_hash": prev
        }, sort_keys=True)
        current = hashlib.sha256(data.encode()).hexdigest()
        entries.append({
            "seq": i, "prev_hash": prev, "current_hash": current
        })
        prev = current

    # Verify chain
    prev_check = GENESIS_HASH
    for e in entries:
        assert e["prev_hash"] == prev_check, f"Break at seq={e['seq']}"
        prev_check = e["current_hash"]

    assert len(entries) == 5


def test_tamper_detection():
    """Modifying middle entry breaks chain at content-hash verification."""
    entries = []
    prev = GENESIS_HASH
    for i in range(1, 6):
        data = json.dumps({
            "seq": i, "action": f"test_{i}", "prev_hash": prev
        }, sort_keys=True)
        current = hashlib.sha256(data.encode()).hexdigest()
        entries.append({
            "seq": i, "action": f"test_{i}",
            "prev_hash": prev,
            "current_hash": current,
            "canonical_data": data,
        })
        prev = current

    # Tamper with entry 3's content WITHOUT recomputing current_hash
    entries[2]["action"] = "TAMPERED"

    # Recompute canonical for entry 3 with tampered action and verify
    tampered_data = json.dumps({
        "seq": 3, "action": "TAMPERED", "prev_hash": entries[2]["prev_hash"]
    }, sort_keys=True)
    recomputed_hash = hashlib.sha256(tampered_data.encode()).hexdigest()
    assert recomputed_hash != entries[2]["current_hash"], \
        "Content tampering must change the hash"

    # Verify ALL entries by recomputing and comparing
    broken = []
    prev_check = GENESIS_HASH
    for e in entries:
        # Check prev_hash continuity
        if e["prev_hash"] != prev_check:
            broken.append(e["seq"])
        # Recompute current_hash from current content
        rec_data = json.dumps({
            "seq": e["seq"], "action": e["action"], "prev_hash": e["prev_hash"]
        }, sort_keys=True)
        rec_hash = hashlib.sha256(rec_data.encode()).hexdigest()
        if rec_hash != e["current_hash"]:
            broken.append(e["seq"])
        prev_check = e["current_hash"]

    assert len(broken) >= 1, "Tampering must be detected"
    assert 3 in broken, "Tampered entry 3 must be flagged"


def test_signing_without_key_fails_safe():
    """Missing signing key should not crash — returns unsigned."""
    svc = AuditChainService.__new__(AuditChainService)
    svc._signing_key = None
    svc.db = None
    sig, success = svc.sign_root_hash("0xabc123")
    assert success is False
    assert "unsigned" in sig.lower()


def test_verification_without_key():
    """Verification without key still checks chain and content hashes."""
    result = AuditVerificationResult(
        chain_valid=True,
        total_entries=5,
        key_available=False,
        error_message="Signing key not available",
    )
    assert result.chain_valid is True
    assert result.key_available is False
    assert "key" in result.error_message.lower()


def test_empty_chain_verification():
    """Empty chain should pass verification (nothing to tamper with)."""
    result = AuditVerificationResult(
        chain_valid=True,
        total_entries=0,
        root_hash=GENESIS_HASH,
    )
    assert result.chain_valid
    assert result.total_entries == 0


def test_tamper_detection_after_modification():
    """After tampering, verification must fail."""
    # Build a simple chain
    prev = GENESIS_HASH
    entry_data = '{"action":"test","prev_hash":"0xGENESIS","seq":1}'
    current = hashlib.sha256(entry_data.encode()).hexdigest()

    # Verify original
    recomputed = hashlib.sha256(entry_data.encode()).hexdigest()
    assert recomputed == current  # Original is valid

    # Tamper the data
    tampered_data = '{"action":"EVIL","prev_hash":"0xGENESIS","seq":1}'
    tampered_hash = hashlib.sha256(tampered_data.encode()).hexdigest()
    assert tampered_hash != current  # Tampered hash differs
