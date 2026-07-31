"""Local administrator utility for Mythic Analyzer accounts."""

from __future__ import annotations

import argparse
import getpass
import secrets
import string

from analyzer_core.auth_store import AuthError, default_auth_store


def generated_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(ch.islower() for ch in value) and any(ch.isupper() for ch in value) and any(ch.isdigit() for ch in value):
            return value


def read_password(confirm: bool = True) -> str:
    password = getpass.getpass("Password: ")
    if confirm and password != getpass.getpass("Confirm password: "):
        raise AuthError("两次输入的密码不一致。")
    return password


def main():
    parser = argparse.ArgumentParser(description="Manage Mythic Analyzer accounts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("username")
    create.add_argument("--role", choices=["viewer", "editor", "admin"], default="viewer")
    create.add_argument("--temporary", action="store_true")

    reset = subparsers.add_parser("reset-password")
    reset.add_argument("username")
    reset.add_argument("--temporary", action="store_true")

    role = subparsers.add_parser("set-role")
    role.add_argument("username")
    role.add_argument("role", choices=["viewer", "editor", "admin"])

    disable = subparsers.add_parser("disable")
    disable.add_argument("username")

    enable = subparsers.add_parser("enable")
    enable.add_argument("username")

    subparsers.add_parser("list")
    args = parser.parse_args()
    store = default_auth_store()

    def selected_user():
        return next((row for row in store.list_users() if row["username"] == args.username.lower()), None)

    try:
        if args.command == "create":
            password = read_password()
            user = store.create_user(
                args.username,
                password,
                role=args.role,
                must_change_password=args.temporary,
            )
            print(f"created {user['username']} ({user['role']})")
        elif args.command == "list":
            for user in store.list_users():
                print(f"{user['id']:>3}  {user['username']:<32} {user['role']:<6} disabled={user['disabled']}")
        else:
            user = selected_user()
            if not user:
                raise AuthError("账号不存在。")
            if args.command == "reset-password":
                store.reset_password(user["id"], read_password(), must_change_password=args.temporary)
                print(f"password reset for {user['username']}")
            elif args.command == "set-role":
                store.set_role(user["id"], args.role)
                print(f"role updated for {user['username']}: {args.role}")
            elif args.command == "disable":
                if user["isAdmin"] and store.admin_count() <= 1:
                    raise AuthError("不能禁用最后一个管理员。")
                store.set_disabled(user["id"], True)
                print(f"disabled {user['username']}")
            elif args.command == "enable":
                store.set_disabled(user["id"], False)
                print(f"enabled {user['username']}")
    except AuthError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
