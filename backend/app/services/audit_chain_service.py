"""Audit signature chain service — tamper-detectable, signed action history.

Implements:
1. Canonical JSON serialization
2. SHA-256 chain linking (each entry depends on previous hash)
3. Ed25519 signing of root hash — **默认启用**（cryptography 可用时自动生成并持久化密钥）
4. Verification: chain continuity, content hash, signature
5. Fail-safe when private key is missing
6. 篡改检测演示：在内存副本上模拟两类攻击，绝不修改数据库真实数据

【签名密钥来源】优先级从高到低：
1. ``AUDIT_SIGNING_KEY_PATH``：指向存放 hex 编码 Ed25519 种子（32 字节）的文件；
2. ``AUDIT_SIGNING_KEY``：hex 编码的 Ed25519 种子；
3. **自动生成并持久化**到 ``backend/.keys/audit_ed25519.key``（0600，已 gitignore）。
   该目录**不在 backend/data/ 内**，不会污染数据集目录。

IMPORTANT: This provides DETECTABLE TAMPER evidence, NOT "blockchain" or
"absolute immutability". We use precise language throughout.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentSpan, AgentTrace, Incident

logger = logging.getLogger(__name__)

GENESIS_HASH = "0xGENESIS"

#: 自动生成的签名密钥落盘目录 —— backend/.keys/（**不是** backend/data/）
BACKEND_DIR = Path(__file__).resolve().parents[2]
KEY_DIR = BACKEND_DIR / ".keys"
DEFAULT_KEY_FILE = KEY_DIR / "audit_ed25519.key"

#: 进程级密钥缓存，避免每个请求都读文件 / 重复生成
_KEY_LOCK = threading.Lock()
_KEY_CACHE: dict[str, Any] | None = None

try:  # pragma: no cover - 取决于运行环境
    from cryptography.hazmat.primitives.asymmetric import ed25519 as _ed25519

    _HAS_ED25519 = True
except Exception:  # pragma: no cover
    _ed25519 = None  # type: ignore[assignment]
    _HAS_ED25519 = False


def _write_key_file(path: Path, seed_hex: str) -> None:
    """把 hex 种子写入密钥文件，并尽力收紧权限（Windows 上 chmod 为 no-op）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    # 目录内自带 .gitignore，确保密钥永远不进版本库
    gitignore = path.parent / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            "# 审计链 Ed25519 签名私钥目录 —— 整个目录（含本文件）都不进版本库\n*\n",
            encoding="utf-8",
        )
    path.write_text(seed_hex, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except Exception:  # pragma: no cover - Windows / 受限文件系统
        pass


def _resolve_signing_key() -> dict[str, Any]:
    """解析 Ed25519 签名密钥（进程内缓存）。

    Returns:
        dict：``{"seed": bytes|None, "source": str, "path": str, "enabled": bool, "reason": str}``
    """
    global _KEY_CACHE
    if _KEY_CACHE is not None:
        return _KEY_CACHE

    with _KEY_LOCK:
        if _KEY_CACHE is not None:
            return _KEY_CACHE

        info: dict[str, Any] = {
            "seed": None,
            "source": "none",
            "path": "",
            "enabled": False,
            "reason": "",
            "algorithm": "Ed25519",
        }

        key_path = os.environ.get("AUDIT_SIGNING_KEY_PATH", "").strip()
        key_env = os.environ.get("AUDIT_SIGNING_KEY", "").strip()

        if key_path and os.path.exists(key_path):
            try:
                raw = Path(key_path).read_text(encoding="utf-8").strip()
                info.update(seed=bytes.fromhex(raw)[:32], source="env:AUDIT_SIGNING_KEY_PATH", path=key_path)
                logger.info("审计签名密钥已从 AUDIT_SIGNING_KEY_PATH 载入")
            except Exception as exc:
                logger.warning(f"无法从文件载入审计签名密钥：{exc}")
        elif key_env:
            try:
                info.update(seed=bytes.fromhex(key_env)[:32], source="env:AUDIT_SIGNING_KEY", path="")
                logger.info("审计签名密钥已从 AUDIT_SIGNING_KEY 环境变量载入")
            except Exception as exc:
                logger.warning(f"无法解码 AUDIT_SIGNING_KEY 环境变量：{exc}")

        # 默认启用：没有显式配置时自动生成并持久化
        if info["seed"] is None and _HAS_ED25519:
            try:
                if DEFAULT_KEY_FILE.exists():
                    raw = DEFAULT_KEY_FILE.read_text(encoding="utf-8").strip()
                    info.update(
                        seed=bytes.fromhex(raw)[:32],
                        source="auto:local_key_file",
                        path=str(DEFAULT_KEY_FILE),
                    )
                    logger.info(f"审计签名密钥已从本地密钥文件载入：{DEFAULT_KEY_FILE}")
                else:
                    seed = os.urandom(32)
                    _write_key_file(DEFAULT_KEY_FILE, seed.hex())
                    info.update(
                        seed=seed,
                        source="auto:generated",
                        path=str(DEFAULT_KEY_FILE),
                    )
                    logger.info(
                        f"未配置审计签名密钥，已自动生成 Ed25519 密钥并持久化到 {DEFAULT_KEY_FILE}"
                        "（该目录已 gitignore，且不在 backend/data/ 内）。"
                        "生产环境请改用 AUDIT_SIGNING_KEY_PATH 指向受管密钥库。"
                    )
            except Exception as exc:
                logger.warning(f"自动生成审计签名密钥失败：{exc}")

        if info["seed"] is None:
            info["reason"] = (
                "cryptography 不可用" if not _HAS_ED25519 else "密钥载入失败"
            ) + "，审计链仍可构建与哈希校验，但无法做根签名。"
            logger.warning(f"审计链根签名未启用：{info['reason']}")
        else:
            info["enabled"] = True

        _KEY_CACHE = info
        return info


def reset_signing_key_cache() -> None:
    """清空进程内签名密钥缓存（测试/密钥轮换后调用）。"""
    global _KEY_CACHE
    with _KEY_LOCK:
        _KEY_CACHE = None


@dataclass
class AuditEntry:
    """One entry in the tamper-detectable audit chain."""
    seq: int
    action_type: str
    agent: str = ""
    input_hash: str = ""
    output_hash: str = ""
    decision: str = ""
    prev_hash: str = ""
    current_hash: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditVerificationResult:
    """Result of audit chain verification."""
    chain_valid: bool = False
    signature_valid: bool = False
    total_entries: int = 0
    first_broken_at: Optional[int] = None
    tampered_entries: list[int] = field(default_factory=list)
    root_hash: str = ""
    key_available: bool = False
    error_message: str = ""
    verified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AuditChainService:
    """Builds and verifies tamper-detectable audit chains.

    Usage:
        svc = AuditChainService(db)
        chain = await svc.build_chain(incident_id)
        verification = await svc.verify(incident_id)
    """

    GENESIS = GENESIS_HASH

    def __init__(self, db: AsyncSession | None = None):
        self.db = db
        self._key_info = _resolve_signing_key()
        self._signing_key: Optional[bytes] = self._key_info.get("seed")

    # ── 密钥信息 ──

    def key_info(self) -> dict[str, Any]:
        """返回签名密钥的**非机密**元信息，供状态端点与前端展示。"""
        return {
            "signing_enabled": bool(self._signing_key),
            "algorithm": "Ed25519",
            "key_source": self._key_info.get("source", "none"),
            "key_path": self._key_info.get("path", ""),
            "public_key": self.public_key_hex(),
            "hash_algorithm": "SHA-256",
            "note": self._key_info.get("reason", "") or "根哈希已使用 Ed25519 私钥签名，可用公钥独立验签。",
        }

    def public_key_hex(self) -> str:
        """返回 Ed25519 公钥（hex）。公钥可安全公开，用于第三方独立验签。"""
        if self._signing_key is None or not _HAS_ED25519:
            return ""
        try:
            from cryptography.hazmat.primitives import serialization

            private_key = _ed25519.Ed25519PrivateKey.from_private_bytes(self._signing_key[:32])
            return private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            ).hex()
        except Exception as exc:  # pragma: no cover - 防御性
            logger.warning(f"导出审计公钥失败：{exc}")
            return ""

    # ── Chain building ──

    async def build_chain(self, incident: Incident) -> list[AuditEntry]:
        """Build audit chain from all agent spans in incident traces.

        Each span becomes one audit entry. Entries are chained via SHA-256.
        The root hash is signed with Ed25519 (if key available).
        """
        # Get all traces for this incident
        traces = await self.db.execute(
            select(AgentTrace).where(AgentTrace.incident_id == incident.id)
        )
        trace_list = traces.scalars().all()

        if not trace_list:
            return []

        # Get all spans from all traces
        all_spans: list[AgentSpan] = []
        for trace in trace_list:
            spans = await self.db.execute(
                select(AgentSpan)
                .where(AgentSpan.trace_id == trace.trace_id)
                .order_by(AgentSpan.step_order.asc(), AgentSpan.started_at.asc())
            )
            all_spans.extend(spans.scalars().all())

        if not all_spans:
            return []

        # Build chain
        chain: list[AuditEntry] = []
        prev_hash = self.GENESIS

        for i, span in enumerate(all_spans, start=1):
            entry_data = self._canonical_json({
                "seq": i,
                "action_type": span.span_name,
                "agent": span.agent_name or "unknown",
                "input_hash": hashlib.sha256(
                    (span.input_digest or "").encode()
                ).hexdigest()[:16],
                "output_hash": hashlib.sha256(
                    (span.output_digest or "").encode()
                ).hexdigest()[:16],
                "decision": span.policy_decision or "",
                "status": span.status,
                "duration_ms": span.duration_ms,
                "timestamp": span.started_at.isoformat() if span.started_at else "",
                "prev_hash": prev_hash,
            })

            current_hash = hashlib.sha256(entry_data.encode()).hexdigest()

            entry = AuditEntry(
                seq=i,
                action_type=span.span_name,
                agent=span.agent_name or "unknown",
                input_hash=hashlib.sha256(
                    (span.input_digest or "").encode()
                ).hexdigest()[:16],
                output_hash=hashlib.sha256(
                    (span.output_digest or "").encode()
                ).hexdigest()[:16],
                decision=span.policy_decision or "",
                prev_hash=prev_hash,
                current_hash=current_hash,
                timestamp=span.started_at or datetime.now(timezone.utc),
                metadata={
                    "span_id": span.span_id,
                    "status": span.status,
                    "duration_ms": span.duration_ms,
                },
            )
            chain.append(entry)
            prev_hash = current_hash

        return chain

    def sign_root_hash(self, root_hash: str) -> tuple[str, bool]:
        """Sign root hash with Ed25519 private key.

        Returns (signature_hex, success).
        If no key available, returns ("unsigned", False).
        """
        if self._signing_key is None:
            return ("unsigned", False)

        try:
            private_key = _ed25519.Ed25519PrivateKey.from_private_bytes(
                self._signing_key[:32]
            )
            signature = private_key.sign(root_hash.encode())
            return (signature.hex(), True)
        except AttributeError:
            logger.warning("cryptography package not available — signature skipped")
            return ("unsigned (no cryptography lib)", False)
        except Exception as e:
            logger.error(f"Signing failed: {e}")
            return (f"error: {e}", False)

    def verify_root_signature(self, root_hash: str, signature_hex: str) -> bool:
        """用公钥验证「某个根哈希 + 某个签名」是否匹配。

        这是**真正的**验签：签名是对原始根哈希做的，只要链上任何一环内容变化
        导致根哈希变化，用旧签名验证新根哈希必然失败——这正是篡改检测演示的核心。
        """
        if self._signing_key is None or not _HAS_ED25519:
            return False
        try:
            private_key = _ed25519.Ed25519PrivateKey.from_private_bytes(self._signing_key[:32])
            private_key.public_key().verify(bytes.fromhex(signature_hex), root_hash.encode())
            return True
        except Exception:
            return False

    # ── Verification ──

    def entry_hash(self, entry: AuditEntry) -> str:
        """按规范化 JSON 重算某一环的内容哈希（与 build_chain 使用同一套字段）。"""
        return hashlib.sha256(
            self._canonical_json({
                "seq": entry.seq,
                "action_type": entry.action_type,
                "agent": entry.agent,
                "input_hash": entry.input_hash,
                "output_hash": entry.output_hash,
                "decision": entry.decision,
                "status": entry.metadata.get("status", ""),
                "duration_ms": entry.metadata.get("duration_ms", 0),
                "timestamp": entry.timestamp.isoformat(),
                "prev_hash": entry.prev_hash,
            }).encode()
        ).hexdigest()

    def inspect_chain(self, chain: list[AuditEntry]) -> dict[str, Any]:
        """逐环校验并返回**结构化**结果（前端可视化直接消费）。

        每一环给出：前驱哈希、当前哈希、重算哈希、链接校验、内容校验、失败原因。
        """
        links: list[dict[str, Any]] = []
        prev = self.GENESIS
        broken: list[int] = []
        first_broken: Optional[int] = None

        for entry in chain:
            link_ok = entry.prev_hash == prev
            recomputed = self.entry_hash(entry)
            hash_ok = recomputed == entry.current_hash
            reasons: list[str] = []
            if not link_ok:
                reasons.append(
                    f"链接断裂：本环记录的前驱哈希 {entry.prev_hash[:16]}… "
                    f"与上一环实际哈希 {prev[:16]}… 不一致"
                )
            if not hash_ok:
                reasons.append(
                    f"内容被改动：重算内容哈希 {recomputed[:16]}… "
                    f"与链上记录的 {entry.current_hash[:16]}… 不一致"
                )
            if not (link_ok and hash_ok):
                broken.append(entry.seq)
                if first_broken is None:
                    first_broken = entry.seq

            links.append({
                "seq": entry.seq,
                "action_type": entry.action_type,
                "agent": entry.agent,
                "decision": entry.decision,
                "input_hash": entry.input_hash,
                "output_hash": entry.output_hash,
                "prev_hash": entry.prev_hash,
                "current_hash": entry.current_hash,
                "recomputed_hash": recomputed,
                "link_ok": link_ok,
                "hash_ok": hash_ok,
                "valid": link_ok and hash_ok,
                "reason": "；".join(reasons) or "通过：前驱链接与内容哈希均一致",
                "timestamp": entry.timestamp.isoformat(),
            })
            prev = entry.current_hash

        root_hash = chain[-1].current_hash if chain else self.GENESIS
        return {
            "total_entries": len(chain),
            "chain_valid": not broken,
            "first_broken_at": first_broken,
            "broken_entries": broken,
            "root_hash": root_hash,
            "links": links,
        }

    async def verify(self, incident: Incident) -> AuditVerificationResult:
        """Verify audit chain integrity.

        Checks:
        1. Chain continuity (each prev_hash matches previous current_hash)
        2. Content hash (recompute and compare)
        3. Ed25519 signature (if key available)
        """
        chain = await self.build_chain(incident)

        if not chain:
            return AuditVerificationResult(
                chain_valid=True,
                total_entries=0,
                root_hash=self.GENESIS,
                key_available=self._signing_key is not None,
            )

        report = self.inspect_chain(chain)
        result = AuditVerificationResult(
            total_entries=report["total_entries"],
            key_available=self._signing_key is not None,
            chain_valid=report["chain_valid"],
            first_broken_at=report["first_broken_at"],
            tampered_entries=list(report["broken_entries"]),
            root_hash=report["root_hash"],
        )

        # Verify signature
        if self._signing_key is not None:
            result.signature_valid = self._verify_signature(result.root_hash)
        else:
            result.error_message = (
                "Signing key not available — signature verification skipped. "
                "Chain continuity and content hashes verified."
            )

        return result

    def _verify_signature(self, root_hash: str) -> bool:
        """Verify Ed25519 signature of root hash (sign-then-verify round trip)."""
        signature, signed = self.sign_root_hash(root_hash)
        if not signed:
            return False
        return self.verify_root_signature(root_hash, signature)

    # ── Tamper detection test ──

    async def simulate_tamper_and_verify(
        self, incident: Incident, tamper_seq: int
    ) -> AuditVerificationResult:
        """Simulate tampering at a specific entry to verify detection.

        Modifies the input_hash of the specified entry, then re-verifies.
        The verification MUST fail.

        注意：篡改只发生在 **build_chain 生成的内存对象** 上，
        AuditEntry 从未落库，因此该操作绝不会修改数据库中的任何真实数据。
        """
        chain = await self.build_chain(incident)
        if tamper_seq < 1 or tamper_seq > len(chain):
            return AuditVerificationResult(
                chain_valid=True,
                error_message=f"Invalid tamper sequence: {tamper_seq}",
            )

        # Tamper: modify the entry's input_hash (simulating content change)
        entry = chain[tamper_seq - 1]
        entry.input_hash = "TAMPERED_" + entry.input_hash
        # Don't recompute current_hash — simulating attacker who doesn't have signing key

        report = self.inspect_chain(chain)
        tampered = list(report["broken_entries"])
        return AuditVerificationResult(
            chain_valid=report["chain_valid"],
            total_entries=report["total_entries"],
            first_broken_at=report["first_broken_at"],
            tampered_entries=tampered,
            root_hash=report["root_hash"],
            key_available=self._signing_key is not None,
            error_message=(
                f"Tampered entry at seq={tamper_seq}. "
                f"Detection: {'SUCCESS' if tampered else 'FAILED'}. "
                f"Broken entries: {tampered}."
            ),
        )

    # ── 篡改检测演示（Demo 第四幕素材）──

    #: 演示中允许被篡改的字段（都是审计链上真实参与哈希计算的字段）
    TAMPERABLE_FIELDS = ("decision", "output_hash", "input_hash", "action_type", "agent")

    def build_demo_chain(self) -> list[AuditEntry]:
        """构造一条**合成**的审计链，用于没有真实 incident 时的演示。

        明确标注为 synthetic，不代表真实风场运行数据。
        """
        base = datetime(2026, 7, 26, 9, 0, 0, tzinfo=timezone.utc)
        blueprint = [
            ("alarm_ingest", "data_agent", "allow", "ok", 180),
            ("root_cause_analysis", "diagnosis_agent", "allow", "ok", 2400),
            ("economic_impact_eval", "decision_agent", "allow", "ok", 610),
            ("maintenance_plan_draft", "planner_agent", "require_confirmation", "ok", 950),
            ("workorder_dispatch", "action_agent", "human_approved", "ok", 320),
        ]
        chain: list[AuditEntry] = []
        prev_hash = self.GENESIS
        for i, (span_name, agent, decision, status, duration) in enumerate(blueprint, start=1):
            entry = AuditEntry(
                seq=i,
                action_type=span_name,
                agent=agent,
                input_hash=hashlib.sha256(f"demo-input-{i}".encode()).hexdigest()[:16],
                output_hash=hashlib.sha256(f"demo-output-{i}".encode()).hexdigest()[:16],
                decision=decision,
                prev_hash=prev_hash,
                timestamp=base.replace(minute=i * 7 % 60),
                metadata={"span_id": f"demo-span-{i}", "status": status, "duration_ms": duration},
            )
            entry.current_hash = self.entry_hash(entry)
            chain.append(entry)
            prev_hash = entry.current_hash
        return chain

    def _sign_block(self, root_hash: str, reference_signature: str = "") -> dict[str, Any]:
        """生成/校验某个根哈希的签名信息块。

        Args:
            root_hash: 待验签的根哈希。
            reference_signature: 若给出，则用它去验签（模拟「攻击者拿不到私钥，
                只能沿用原始签名」的场景）；否则现签现验。
        """
        if not self._signing_key:
            return {
                "algorithm": "Ed25519",
                "enabled": False,
                "signature": "unsigned",
                "verified": False,
                "note": "未启用根签名，仅完成 SHA-256 链校验。",
            }
        if reference_signature:
            verified = self.verify_root_signature(root_hash, reference_signature)
            return {
                "algorithm": "Ed25519",
                "enabled": True,
                "signature": reference_signature,
                "verified": verified,
                "note": (
                    "使用原始根签名验签通过。" if verified
                    else "使用原始根签名验签失败：根哈希已变化，攻击者无私钥无法重新签名。"
                ),
            }
        signature, ok = self.sign_root_hash(root_hash)
        return {
            "algorithm": "Ed25519",
            "enabled": True,
            "signature": signature,
            "verified": ok and self.verify_root_signature(root_hash, signature),
            "note": "根哈希已用 Ed25519 私钥签名，可用公钥独立验签。",
        }

    def tamper_scenarios(
        self,
        chain: list[AuditEntry],
        tamper_seq: int,
        tamper_field: str = "decision",
        tamper_value: str = "auto_approved_without_human",
    ) -> dict[str, Any]:
        """在**内存副本**上跑两类篡改场景，返回适合前端可视化的结构化对比。

        场景一 `content_tamper`：攻击者改了动作内容但没有重算哈希
            → 第 N 环内容哈希重算不一致，当场暴露。
        场景二 `hash_recompute`：攻击者改内容后重算了第 N 环哈希
            → 第 N 环自身「看起来合法」，但第 N+1 环前驱链接断裂。
        场景三 `full_rechain`：攻击者重算了第 N 环及其**全部下游**哈希，伪造出一条自洽的链
            → 纯哈希校验**全部通过**，但根哈希已变化，
              用原始 Ed25519 签名验签必然失败（攻击者没有私钥，无法重新签名）。
              这一场景是「为什么必须默认启用根签名」的直接证据。

        **绝不修改数据库**：AuditEntry 是内存 dataclass，这里还额外做了 deepcopy。
        """
        if tamper_field not in self.TAMPERABLE_FIELDS:
            tamper_field = "decision"

        baseline_report = self.inspect_chain(chain)
        baseline_signature = self._sign_block(baseline_report["root_hash"])
        baseline_report["signature"] = baseline_signature

        scenarios: list[dict[str, Any]] = []
        if 1 <= tamper_seq <= len(chain):
            original_value = getattr(chain[tamper_seq - 1], tamper_field)

            # 场景一：只改内容，不重算哈希
            c1 = copy.deepcopy(chain)
            setattr(c1[tamper_seq - 1], tamper_field, tamper_value)
            r1 = self.inspect_chain(c1)
            r1["signature"] = self._sign_block(
                r1["root_hash"], baseline_signature.get("signature", "") if baseline_signature.get("enabled") else ""
            )
            scenarios.append({
                "id": "content_tamper",
                "name": "场景一：篡改动作内容，不重算哈希",
                "attacker_capability": "拥有数据库写权限，但不了解链式哈希结构",
                "tamper": {
                    "seq": tamper_seq,
                    "field": tamper_field,
                    "before": original_value,
                    "after": tamper_value,
                },
                "result": r1,
                "detected": not r1["chain_valid"],
                "detected_by": ["content_hash"],
                "conclusion": (
                    f"第 {r1['first_broken_at']} 环内容哈希重算不一致，篡改被立即检出。"
                    if not r1["chain_valid"] else "未检出（异常，应当检出）"
                ),
            })

            # 场景二：改内容并重算该环哈希（更高明的攻击者）
            c2 = copy.deepcopy(chain)
            setattr(c2[tamper_seq - 1], tamper_field, tamper_value)
            c2[tamper_seq - 1].current_hash = self.entry_hash(c2[tamper_seq - 1])
            r2 = self.inspect_chain(c2)
            r2["signature"] = self._sign_block(
                r2["root_hash"], baseline_signature.get("signature", "") if baseline_signature.get("enabled") else ""
            )
            downstream_broken = bool(r2["broken_entries"])
            signature_broken = baseline_signature.get("enabled") and not r2["signature"]["verified"]
            detected_by = []
            if downstream_broken:
                detected_by.append("chain_linkage")
            if signature_broken:
                detected_by.append("root_signature")
            scenarios.append({
                "id": "hash_recompute",
                "name": "场景二：篡改内容并重算该环哈希",
                "attacker_capability": "拥有数据库写权限，且懂链式哈希，但**没有 Ed25519 私钥**",
                "tamper": {
                    "seq": tamper_seq,
                    "field": tamper_field,
                    "before": original_value,
                    "after": tamper_value,
                    "recomputed_hash": True,
                },
                "result": r2,
                "detected": bool(detected_by),
                "detected_by": detected_by,
                "conclusion": (
                    (f"第 {r2['first_broken_at']} 环前驱链接断裂，篡改被检出。" if downstream_broken else "")
                    + ("根哈希已变化，原始 Ed25519 签名验签失败。" if signature_broken else "")
                ) or "未检出（异常，应当检出）",
            })

            # 场景三：重算第 N 环及全部下游，伪造一条内部自洽的链
            c3 = copy.deepcopy(chain)
            setattr(c3[tamper_seq - 1], tamper_field, tamper_value)
            prev_hash = c3[tamper_seq - 2].current_hash if tamper_seq >= 2 else self.GENESIS
            for entry in c3[tamper_seq - 1:]:
                entry.prev_hash = prev_hash
                entry.current_hash = self.entry_hash(entry)
                prev_hash = entry.current_hash
            r3 = self.inspect_chain(c3)
            r3["signature"] = self._sign_block(
                r3["root_hash"], baseline_signature.get("signature", "") if baseline_signature.get("enabled") else ""
            )
            root_changed = r3["root_hash"] != baseline_report["root_hash"]
            sig3_broken = bool(baseline_signature.get("enabled")) and not r3["signature"]["verified"]
            detected_by3 = ["root_signature"] if sig3_broken else []
            scenarios.append({
                "id": "full_rechain",
                "name": "场景三：重算整条下游链，伪造自洽审计链",
                "attacker_capability": "拥有数据库写权限，完全掌握链式哈希算法，但**没有 Ed25519 私钥**",
                "tamper": {
                    "seq": tamper_seq,
                    "field": tamper_field,
                    "before": original_value,
                    "after": tamper_value,
                    "recomputed_hash": True,
                    "rechained_downstream": True,
                },
                "result": r3,
                "detected": bool(detected_by3),
                "detected_by": detected_by3,
                "hash_only_check_passed": r3["chain_valid"],
                "root_hash_changed": root_changed,
                "conclusion": (
                    "纯 SHA-256 链校验**全部通过**（攻击者伪造出自洽的链），"
                    f"但根哈希由 {baseline_report['root_hash'][:16]}… 变为 {r3['root_hash'][:16]}…，"
                    "用原始 Ed25519 签名验签失败——攻击者没有私钥，无法伪造新签名。"
                    "这正是根签名必须默认启用的原因。"
                    if sig3_broken else
                    "未检出：当前未启用 Ed25519 根签名，仅靠哈希链无法识别「整条链被重写」这类攻击。"
                ),
            })

        detected_all = bool(scenarios) and all(s["detected"] for s in scenarios)
        return {
            "baseline": baseline_report,
            "scenarios": scenarios,
            "summary": {
                "baseline_chain_valid": baseline_report["chain_valid"],
                "baseline_signature_verified": baseline_signature.get("verified", False),
                "scenarios_total": len(scenarios),
                "scenarios_detected": sum(1 for s in scenarios if s["detected"]),
                "all_detected": detected_all,
                "headline": (
                    f"篡改前：{baseline_report['total_entries']} 环全链校验通过"
                    + ("，Ed25519 根签名验签通过。" if baseline_signature.get("verified") else "。")
                    + f" 篡改后：{sum(1 for s in scenarios if s['detected'])}/{len(scenarios)} 种攻击场景均被检出"
                    + f"（篡改点：第 {tamper_seq} 环 {tamper_field}）。"
                ),
            },
            "database_mutated": False,
            "safety_note": (
                "篡改仅发生在内存中的审计链副本（deepcopy）上，"
                "数据库中的 agent_spans / agent_traces 记录未被读写以外的任何操作影响。"
            ),
        }

    # ── Helpers ──

    @staticmethod
    def _canonical_json(data: dict[str, Any]) -> str:
        """Canonical JSON serialization: sorted keys, no whitespace, deterministic."""
        return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
