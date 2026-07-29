"""密钥静态加密模块 —— API Key at-rest encryption。

【背景】
`users.api_key` 与 `ai_provider_configs.api_key` 原先是明文列，直接写入 SQLite。
数据库文件一旦泄漏就等于密钥泄漏。本模块提供对称加密能力，并以 SQLAlchemy
``TypeDecorator`` 的形式挂到上述两列上，实现「写时加密、读时解密」，
对上层业务代码完全透明（agent / ai / settings / workorders 等读取路径无需感知）。

【向后兼容 —— 硬要求】
- 密文统一带前缀 ``enc:v1:``（Fernet）或 ``enc:v1f:``（无 cryptography 时的
  标准库回退方案）。读取时若没有前缀，视为**历史明文**，原样返回，照常可用。
- 用户下一次保存/更新密钥时会走写入路径，自动升级为密文（读时兼容、写时升级）。
- **不做任何数据库批量迁移**，绝不改动既有数据行。

【密钥来源】
1. 环境变量 ``PHM_ENCRYPTION_KEY``（推荐）。既接受标准 Fernet key
   （urlsafe-base64 的 32 字节），也接受任意长度口令（内部再做一次 PBKDF2 派生）。
2. 未设置时，从 ``settings.SECRET_KEY`` 通过 PBKDF2-HMAC-SHA256 派生，
   并在日志打 warning 提示生产环境应显式设置 ``PHM_ENCRYPTION_KEY``。

【算法】
- 首选 ``cryptography`` 的 Fernet：AES-128-CBC + HMAC-SHA256（Encrypt-then-MAC）。
- 回退方案（无 cryptography 时）：纯标准库实现的
  HMAC-SHA256 计数器模式流加密 + HMAC-SHA256 认证标签，同样是 Encrypt-then-MAC，
  不引入任何第三方依赖。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from functools import lru_cache
from typing import Any, Optional

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── 常量 ──

#: Fernet 密文前缀（cryptography 可用时使用）
ENC_PREFIX = "enc:v1:"
#: 标准库回退方案密文前缀（fallback，f = fallback）
ENC_PREFIX_FALLBACK = "enc:v1f:"
#: 所有已知密文前缀，读取时按此判定「明文 vs 密文」
KNOWN_PREFIXES = (ENC_PREFIX, ENC_PREFIX_FALLBACK)

#: PBKDF2 固定盐值。必须固定，否则进程重启后无法解密既有密文。
#: 盐值公开不影响安全性——它的作用是域分离与抗彩虹表，机密性由 SECRET_KEY / PHM_ENCRYPTION_KEY 承担。
_KDF_SALT = b"fengdiao-phm-apikey-at-rest-v1"
_KDF_ITERATIONS = 200_000

_DEV_SECRET = "fengdiao-phm-dev-secret-key-change-in-production"

try:  # pragma: no cover - 取决于运行环境
    from cryptography.fernet import Fernet, InvalidToken

    _HAS_CRYPTOGRAPHY = True
except Exception:  # pragma: no cover
    Fernet = None  # type: ignore[assignment]
    InvalidToken = Exception  # type: ignore[assignment]
    _HAS_CRYPTOGRAPHY = False


# ── 密钥派生 ──


def _derive_key(material: str | bytes, info: bytes = b"apikey") -> bytes:
    """用 PBKDF2-HMAC-SHA256 从口令派生 32 字节密钥（确定性，重启后可复现）。"""
    if isinstance(material, str):
        material = material.encode("utf-8")
    return hashlib.pbkdf2_hmac(
        "sha256", material, _KDF_SALT + b"|" + info, _KDF_ITERATIONS, dklen=32
    )


@lru_cache(maxsize=1)
def _key_material() -> tuple[bytes, str]:
    """返回 (32字节主密钥, 来源说明)。

    优先级：PHM_ENCRYPTION_KEY 环境变量 > 从 SECRET_KEY 派生。
    """
    env_key = (os.environ.get("PHM_ENCRYPTION_KEY") or "").strip()
    if env_key:
        # 允许直接给标准 Fernet key（44 字符 urlsafe-base64），否则当作口令再派生一次
        try:
            raw = base64.urlsafe_b64decode(env_key.encode("ascii"))
            if len(raw) == 32:
                return raw, "env:PHM_ENCRYPTION_KEY(fernet_key)"
        except Exception:
            pass
        return _derive_key(env_key), "env:PHM_ENCRYPTION_KEY(passphrase)"

    secret = get_settings().SECRET_KEY
    if secret == _DEV_SECRET:
        logger.warning(
            "PHM_ENCRYPTION_KEY 未设置，且 SECRET_KEY 仍为开发默认值——"
            "API Key 加密强度等同于公开密钥。生产环境必须显式设置 PHM_ENCRYPTION_KEY。"
        )
    else:
        logger.warning(
            "PHM_ENCRYPTION_KEY 未设置，已从 SECRET_KEY 通过 PBKDF2 派生加密密钥。"
            "生产环境建议显式设置 PHM_ENCRYPTION_KEY，避免轮换 SECRET_KEY 时导致已存密钥无法解密。"
        )
    return _derive_key(secret), "derived:SECRET_KEY(PBKDF2-HMAC-SHA256)"


@lru_cache(maxsize=1)
def _fernet() -> Any:
    """构造并缓存 Fernet 实例（cryptography 不可用时返回 None）。"""
    if not _HAS_CRYPTOGRAPHY:
        return None
    key, _ = _key_material()
    return Fernet(base64.urlsafe_b64encode(key))


# ── 标准库回退方案（HMAC-SHA256 CTR 流加密 + HMAC 认证标签）──


def _fallback_keys() -> tuple[bytes, bytes]:
    master, _ = _key_material()
    return _derive_key(master, b"stream-enc"), _derive_key(master, b"stream-mac")


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(
            enc_key, nonce + counter.to_bytes(8, "big"), hashlib.sha256
        ).digest()
        counter += 1
    return bytes(out[:length])


def _fallback_encrypt(plain: str) -> str:
    enc_key, mac_key = _fallback_keys()
    nonce = os.urandom(16)
    data = plain.encode("utf-8")
    cipher = bytes(a ^ b for a, b in zip(data, _keystream(enc_key, nonce, len(data))))
    tag = hmac.new(mac_key, nonce + cipher, hashlib.sha256).digest()
    return ENC_PREFIX_FALLBACK + base64.urlsafe_b64encode(nonce + cipher + tag).decode("ascii")


def _fallback_decrypt(token: str) -> str:
    enc_key, mac_key = _fallback_keys()
    raw = base64.urlsafe_b64decode(token[len(ENC_PREFIX_FALLBACK):].encode("ascii"))
    nonce, cipher, tag = raw[:16], raw[16:-32], raw[-32:]
    expected = hmac.new(mac_key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("认证标签校验失败：密文被篡改或加密密钥不匹配")
    return bytes(
        a ^ b for a, b in zip(cipher, _keystream(enc_key, nonce, len(cipher)))
    ).decode("utf-8")


# ── 对外 API ──


def crypto_backend() -> str:
    """返回当前使用的加密后端标识，便于自检与运维排查。"""
    return "fernet(AES-128-CBC+HMAC-SHA256)" if _HAS_CRYPTOGRAPHY else "stdlib(HMAC-SHA256-CTR+HMAC)"


def key_source() -> str:
    """返回加密密钥来源说明（不含密钥本身）。"""
    return _key_material()[1]


def is_encrypted(value: Optional[str]) -> bool:
    """判断存储值是密文还是历史明文。"""
    return bool(value) and value.startswith(KNOWN_PREFIXES)


def encrypt_secret(plain: Optional[str]) -> Optional[str]:
    """加密密钥明文。

    - ``None`` / 空串原样返回（不把空值变成密文，保持 ``bool(api_key)`` 语义）。
    - 已是密文则直接返回，避免重复加密。
    - 加密失败时**降级为原样存储**并记录 error，绝不因为加密问题丢失用户密钥。
    """
    if not plain:
        return plain
    if is_encrypted(plain):
        return plain
    try:
        cipher = _fernet()
        if cipher is not None:
            return ENC_PREFIX + cipher.encrypt(plain.encode("utf-8")).decode("ascii")
        return _fallback_encrypt(plain)
    except Exception as exc:  # pragma: no cover - 防御性分支
        logger.error(f"API Key 加密失败，退化为明文存储：{exc}")
        return plain


def decrypt_secret(stored: Optional[str]) -> Optional[str]:
    """解密存储值。

    - 无前缀 → **历史明文**，原样返回（向后兼容，绝不让既有密钥失效）。
    - 有前缀但解密失败 → 记录 warning 并返回 ``None``，避免把密文当密钥发给上游供应商。
    """
    if not stored:
        return stored
    if not is_encrypted(stored):
        return stored  # 历史明文，照常可用
    try:
        if stored.startswith(ENC_PREFIX_FALLBACK):
            return _fallback_decrypt(stored)
        cipher = _fernet()
        if cipher is None:
            logger.warning("检测到 Fernet 密文，但当前环境缺少 cryptography 库，无法解密")
            return None
        return cipher.decrypt(stored[len(ENC_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.warning("API Key 解密失败（密钥不匹配或密文损坏），已按未配置处理")
        return None
    except Exception as exc:
        logger.warning(f"API Key 解密失败：{exc}")
        return None


def mask_secret(value: Optional[str], keep: int = 4) -> str:
    """脱敏展示：只保留尾部若干位，用于日志与 API 响应。"""
    plain = decrypt_secret(value)
    if not plain:
        return ""
    if len(plain) <= keep:
        return "*" * len(plain)
    return "*" * (len(plain) - keep) + plain[-keep:]


# ── SQLAlchemy 透明加密列类型 ──


class EncryptedSecret(TypeDecorator):
    """透明加密的字符串列类型：写入自动加密，读取自动解密。

    历史明文行会被原样读出（兼容），并在下一次写入时自动升级为密文。
    """

    impl = String
    cache_ok = True

    def __init__(self, length: int = 1024, **kwargs: Any) -> None:
        super().__init__(length=length, **kwargs)

    def process_bind_param(self, value, dialect):  # noqa: D102 - 见类 docstring
        return encrypt_secret(value)

    def process_result_value(self, value, dialect):  # noqa: D102
        return decrypt_secret(value)


def mark_secret_for_upgrade(instance: Any, attr: str = "api_key") -> bool:
    """强制把某个密钥字段标记为「已修改」，让本次 flush 一定重写该列。

    用途：历史明文行被 ORM 读出后在 Python 侧是明文，无法区分「库里本来就是明文」
    还是「刚解密出来的密文」。在任何保存路径上调用本函数，即可保证这一行落盘时
    必然经过 :class:`EncryptedSecret` 的加密处理，实现「读时兼容、写时升级」，
    而无需任何批量迁移脚本去改动既有数据。

    Returns:
        True 表示已标记（字段有值），False 表示字段为空、无需处理。
    """
    if not getattr(instance, attr, None):
        return False
    try:
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(instance, attr)
        return True
    except Exception as exc:  # pragma: no cover - 防御性
        logger.debug(f"标记密钥字段升级失败：{exc}")
        return False


#: 需要静态加密的列：(表名, 列名)
ENCRYPTED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("users", "api_key"),
    ("ai_provider_configs", "api_key"),
)

_installed = False


def install_encrypted_columns() -> list[str]:
    """把 :class:`EncryptedSecret` 挂到目标列上（幂等）。

    在任何 SQL 语句编译之前调用，之后所有 ORM 读写自动加解密。
    这样做的好处是**不需要改动 models 定义**，也不需要在每个读取点手工解密。

    Returns:
        实际完成挂载的 ``表.列`` 列表。
    """
    global _installed
    if _installed:
        return []

    from app.database import Base  # 延迟导入，避免循环依赖
    import app.models  # noqa: F401  确保表已注册到 metadata

    patched: list[str] = []
    for table_name, column_name in ENCRYPTED_COLUMNS:
        table = Base.metadata.tables.get(table_name)
        if table is None:
            logger.debug(f"加密列挂载跳过：表 {table_name} 未注册")
            continue
        column = table.c.get(column_name)
        if column is None:
            logger.debug(f"加密列挂载跳过：{table_name}.{column_name} 不存在")
            continue
        if isinstance(column.type, EncryptedSecret):
            continue
        column.type = EncryptedSecret(max(getattr(column.type, "length", 512) or 512, 1024))
        patched.append(f"{table_name}.{column_name}")

    _installed = True
    if patched:
        logger.info(
            f"API Key 静态加密已启用（{crypto_backend()} / {key_source()}）：{', '.join(patched)}"
        )
    return patched


# 模块导入即安装，保证任何 import 了本模块的入口都受保护。
try:  # pragma: no cover - 防御性
    install_encrypted_columns()
except Exception as _exc:  # pragma: no cover
    logger.error(f"API Key 静态加密挂载失败，将退回明文存储：{_exc}")
