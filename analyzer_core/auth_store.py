"""Local account, session, and encrypted WCL credential storage."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from analyzer_core.wcl_context import WclCredentials


ROOT = Path(__file__).resolve().parents[1]
AUTH_DIR = Path(os.getenv("APP_AUTH_DIR") or (ROOT / "auth"))
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
PASSWORD_MIN_LENGTH = 12
SESSION_HOURS = max(1, int(os.getenv("APP_SESSION_HOURS", "24") or 24))
ROLES = {"viewer", "editor", "admin"}


class AuthError(ValueError):
    pass


def normalize_username(username: str) -> str:
    value = str(username or "").strip().lower()
    if not USERNAME_RE.fullmatch(value):
        raise AuthError("用户名只能包含字母、数字、点、下划线或横线，长度为 3–32。")
    return value


def validate_password(password: str) -> str:
    value = str(password or "")
    if len(value) < PASSWORD_MIN_LENGTH:
        raise AuthError(f"密码至少需要 {PASSWORD_MIN_LENGTH} 个字符。")
    if value.lower() == value or value.upper() == value or not any(ch.isdigit() for ch in value):
        raise AuthError("密码需要同时包含大小写字母和数字。")
    return value


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("ascii"))


def hash_password(password: str) -> str:
    password = validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**15,
        r=8,
        p=1,
        dklen=64,
        maxmem=128 * 1024 * 1024,
    )
    return f"scrypt$32768$8$1${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            str(password or "").encode("utf-8"),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_unb64(expected)),
            maxmem=128 * 1024 * 1024,
        )
        return hmac.compare_digest(digest, _unb64(expected))
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


class AuthStore:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        key_path: Optional[Path] = None,
        session_hours: int = SESSION_HOURS,
    ):
        self.db_path = Path(db_path or (AUTH_DIR / "auth.db"))
        self.key_path = Path(key_path or (AUTH_DIR / "master.key"))
        self.session_seconds = max(1, int(session_hours)) * 3600
        self._init_lock = threading.Lock()
        self._fernet: Optional[Fernet] = None
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def _initialize(self):
        with self._init_lock:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        password_hash TEXT NOT NULL,
                        is_admin INTEGER NOT NULL DEFAULT 0,
                        can_modify INTEGER NOT NULL DEFAULT 0,
                        disabled INTEGER NOT NULL DEFAULT 0,
                        must_change_password INTEGER NOT NULL DEFAULT 0,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS sessions (
                        token_hash TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        created_at INTEGER NOT NULL,
                        expires_at INTEGER NOT NULL,
                        last_seen_at INTEGER NOT NULL,
                        remote_address TEXT NOT NULL DEFAULT '',
                        user_agent TEXT NOT NULL DEFAULT '',
                        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS sessions_user_id ON sessions(user_id);
                    CREATE INDEX IF NOT EXISTS sessions_expires_at ON sessions(expires_at);
                    CREATE TABLE IF NOT EXISTS wcl_credentials (
                        user_id INTEGER PRIMARY KEY,
                        client_id_cipher TEXT NOT NULL,
                        client_secret_cipher TEXT NOT NULL,
                        updated_at INTEGER NOT NULL,
                        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                    );
                    """
                )
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(users)").fetchall()
                }
                if "can_modify" not in columns:
                    connection.execute(
                        "ALTER TABLE users ADD COLUMN can_modify INTEGER NOT NULL DEFAULT 0"
                    )
                connection.commit()
            try:
                os.chmod(self.db_path.parent, 0o700)
            except OSError:
                pass

    def _cipher(self) -> Fernet:
        if self._fernet:
            return self._fernet
        configured = str(os.getenv("APP_ENCRYPTION_KEY") or "").strip().encode("ascii")
        if configured:
            key = configured
        else:
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with self.key_path.open("xb") as handle:
                    handle.write(Fernet.generate_key())
            except FileExistsError:
                pass
            key = self.key_path.read_bytes().strip()
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass
        try:
            self._fernet = Fernet(key)
        except (ValueError, TypeError) as error:
            raise RuntimeError("APP_ENCRYPTION_KEY 或 auth/master.key 无效。") from error
        return self._fernet

    @staticmethod
    def _public_user(row: sqlite3.Row) -> dict:
        role = "admin" if row["is_admin"] else ("editor" if row["can_modify"] else "viewer")
        return {
            "id": int(row["id"]),
            "username": row["username"],
            "isAdmin": bool(row["is_admin"]),
            "canModify": bool(row["is_admin"] or row["can_modify"]),
            "role": role,
            "disabled": bool(row["disabled"]),
            "mustChangePassword": bool(row["must_change_password"]),
        }

    def create_user(
        self,
        username: str,
        password: str,
        *,
        is_admin: bool = False,
        role: Optional[str] = None,
        must_change_password: bool = False,
    ) -> dict:
        username = normalize_username(username)
        selected_role = str(role or ("admin" if is_admin else "viewer")).strip().lower()
        if selected_role not in ROLES:
            raise AuthError("账号权限必须是 viewer、editor 或 admin。")
        encoded = hash_password(password)
        now = int(time.time())
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO users(
                        username, password_hash, is_admin, can_modify, must_change_password,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        encoded,
                        int(selected_role == "admin"),
                        int(selected_role in {"admin", "editor"}),
                        int(must_change_password),
                        now,
                        now,
                    ),
                )
                user_id = int(cursor.lastrowid)
                connection.commit()
        except sqlite3.IntegrityError as error:
            raise AuthError("该用户名已经存在。") from error
        return self.get_user(user_id)

    def get_user(self, user_id: int) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
        return self._public_user(row) if row else None

    def list_users(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [self._public_user(row) for row in rows]

    def authenticate(self, username: str, password: str) -> Optional[dict]:
        try:
            username = normalize_username(username)
        except AuthError:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
        if not row or row["disabled"] or not verify_password(password, row["password_hash"]):
            return None
        return self._public_user(row)

    def create_session(self, user_id: int, remote_address: str = "", user_agent: str = "") -> str:
        token = secrets.token_urlsafe(48)
        now = int(time.time())
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            connection.execute(
                """
                INSERT INTO sessions(
                    token_hash, user_id, created_at, expires_at, last_seen_at,
                    remote_address, user_agent
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _token_hash(token),
                    int(user_id),
                    now,
                    now + self.session_seconds,
                    now,
                    str(remote_address or "")[:200],
                    str(user_agent or "")[:500],
                ),
            )
            connection.commit()
        return token

    def session_user(self, token: str) -> Optional[dict]:
        if not token:
            return None
        now = int(time.time())
        token_digest = _token_hash(token)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT users.*, sessions.last_seen_at
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                """,
                (token_digest, now),
            ).fetchone()
            if not row or row["disabled"]:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_digest,))
                connection.commit()
                return None
            if now - int(row["last_seen_at"]) >= 300:
                connection.execute(
                    "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                    (now, token_digest),
                )
                connection.commit()
        return self._public_user(row)

    def delete_session(self, token: str):
        if not token:
            return
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
            connection.commit()

    def delete_user_sessions(self, user_id: int):
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))
            connection.commit()

    def change_password(self, user_id: int, current_password: str, new_password: str):
        with self._connect() as connection:
            row = connection.execute("SELECT password_hash FROM users WHERE id = ?", (int(user_id),)).fetchone()
            if not row or not verify_password(current_password, row["password_hash"]):
                raise AuthError("当前密码不正确。")
            encoded = hash_password(new_password)
            connection.execute(
                """
                UPDATE users
                SET password_hash = ?, must_change_password = 0, updated_at = ?
                WHERE id = ?
                """,
                (encoded, int(time.time()), int(user_id)),
            )
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))
            connection.commit()

    def reset_password(self, user_id: int, new_password: str, *, must_change_password: bool = True):
        encoded = hash_password(new_password)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE users
                SET password_hash = ?, must_change_password = ?, updated_at = ?
                WHERE id = ?
                """,
                (encoded, int(must_change_password), int(time.time()), int(user_id)),
            )
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))
            connection.commit()

    def set_disabled(self, user_id: int, disabled: bool):
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET disabled = ?, updated_at = ? WHERE id = ?",
                (int(disabled), int(time.time()), int(user_id)),
            )
            if disabled:
                connection.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))
            connection.commit()

    def set_role(self, user_id: int, role: str, *, actor_user_id: Optional[int] = None):
        role = str(role or "").strip().lower()
        if role not in ROLES:
            raise AuthError("账号权限必须是只读、可修改或管理员。")
        user_id = int(user_id)
        if actor_user_id is not None and int(actor_user_id) == user_id and role != "admin":
            raise AuthError("管理员不能降低自己的权限。")
        with self._connect() as connection:
            row = connection.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                raise AuthError("账号不存在。")
            connection.execute(
                """
                UPDATE users
                SET is_admin = ?, can_modify = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    int(role == "admin"),
                    int(role in {"admin", "editor"}),
                    int(time.time()),
                    user_id,
                ),
            )
            connection.commit()

    def admin_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM users WHERE is_admin = 1 AND disabled = 0"
            ).fetchone()
        return int(row["count"])

    def set_wcl_credentials(self, user_id: int, client_id: str, client_secret: str):
        client_id = str(client_id or "").strip()
        client_secret = str(client_secret or "").strip()
        if not client_id or not client_secret:
            raise AuthError("WCL Client ID 和 Client Secret 都不能为空。")
        cipher = self._cipher()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO wcl_credentials(
                    user_id, client_id_cipher, client_secret_cipher, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    client_id_cipher = excluded.client_id_cipher,
                    client_secret_cipher = excluded.client_secret_cipher,
                    updated_at = excluded.updated_at
                """,
                (
                    int(user_id),
                    cipher.encrypt(client_id.encode("utf-8")).decode("ascii"),
                    cipher.encrypt(client_secret.encode("utf-8")).decode("ascii"),
                    int(time.time()),
                ),
            )
            connection.commit()

    def get_wcl_credentials(self, user_id: int) -> Optional[WclCredentials]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT client_id_cipher, client_secret_cipher FROM wcl_credentials WHERE user_id = ?",
                (int(user_id),),
            ).fetchone()
        if not row:
            return None
        cipher = self._cipher()
        try:
            return WclCredentials(
                client_id=cipher.decrypt(row["client_id_cipher"].encode("ascii")).decode("utf-8"),
                client_secret=cipher.decrypt(row["client_secret_cipher"].encode("ascii")).decode("utf-8"),
            )
        except (InvalidToken, ValueError) as error:
            raise RuntimeError("当前账号的 WCL 凭据无法解密，请重新保存。") from error

    def wcl_summary(self, user_id: int) -> dict:
        credentials = self.get_wcl_credentials(user_id)
        if not credentials:
            return {"configured": False, "clientIdHint": ""}
        client_id = credentials.client_id
        hint = client_id[:4] + "…" + client_id[-4:] if len(client_id) > 10 else "已配置"
        return {"configured": True, "clientIdHint": hint}

    def delete_wcl_credentials(self, user_id: int):
        with self._connect() as connection:
            connection.execute("DELETE FROM wcl_credentials WHERE user_id = ?", (int(user_id),))
            connection.commit()


_DEFAULT_STORE: Optional[AuthStore] = None
_DEFAULT_STORE_LOCK = threading.Lock()


def default_auth_store() -> AuthStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        with _DEFAULT_STORE_LOCK:
            if _DEFAULT_STORE is None:
                _DEFAULT_STORE = AuthStore()
    return _DEFAULT_STORE
