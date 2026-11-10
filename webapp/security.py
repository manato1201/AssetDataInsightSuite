"""webapp/security.py

認証を持たないローカル GUI(127.0.0.1)を、ブラウザ経由の攻撃から守る最小限の検査
(ToolOrchestrationHub の hub/security.py と同じ考え方。2026-11-10 に移植)。

この GUI は ``POST /scan``(指定ディレクトリの走査)、``POST /rules/<file>/edit``(ルール定義の書き換え)、
``POST /runs/<id>/notify``(Webhook 送信)を持つ。ブラウザで別のサイトを開いているだけで、そのページが
``<form method=post action=http://localhost:5000/...>`` を自動送信できると、意図しない操作が走りうる。

- **Host ヘッダの許可リスト**: 既定はループバックのみ(DNS rebinding 対策)。別のホスト名で開くときは
  環境変数 ``INSIGHT_ALLOWED_HOSTS``(カンマ区切り。ポートは無視)に足す。
- **変更操作(POST/PUT/PATCH/DELETE)の Origin** が、このリクエスト自身の Host と一致すること。
  ブラウザは別サイトからのフォーム送信にも Origin を付ける。Origin を付けないクライアント
  (curl・テスト・CI)は通す。``Origin: null`` は弾く。

これは**認証ではない**。複数人で使う場合は、この上に認証と役割(スキャン・ルール編集をできる人)が要る。
"""
from __future__ import annotations

import os
from collections.abc import Iterable
from urllib.parse import urlsplit

from flask import Flask, jsonify, request

ALLOWED_HOSTS_ENV = "INSIGHT_ALLOWED_HOSTS"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def host_only(host_header: str) -> str:
    """Host ヘッダからポートを除いたホスト名を小文字で返す(``[::1]:5000`` → ``::1``)。"""
    host = host_header.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end != -1 else host
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host


def resolve_allowed_hosts(extra: Iterable[str] | None = None) -> frozenset[str]:
    """ループバック + 環境変数 INSIGHT_ALLOWED_HOSTS + 引数の許可ホスト。"""
    allowed = set(LOOPBACK_HOSTS)
    for item in [*os.environ.get(ALLOWED_HOSTS_ENV, "").split(","), *(extra or [])]:
        item = item.strip()
        if item:
            allowed.add(host_only(item))
    return frozenset(allowed)


def is_same_origin(origin: str, host_header: str) -> bool:
    """Origin のホストとポートが Host ヘッダと一致するか(スキームは見ない)。``null`` は常に不一致。"""
    if origin.strip().lower() == "null":
        return False
    return urlsplit(origin).netloc.lower() == host_header.strip().lower()


def install_request_guard(app: Flask) -> None:
    """全リクエストの Host と、変更操作の Origin を検査する before_request を入れる。"""

    @app.before_request
    def _request_guard():
        host_header = request.headers.get("Host", "")
        if host_only(host_header) not in resolve_allowed_hosts():
            return (
                jsonify(
                    error=(
                        f"この Host では受け付けません: {host_header!r}。"
                        f"127.0.0.1 / localhost 以外のホスト名で開く場合は、環境変数 {ALLOWED_HOSTS_ENV} に追加してください"
                    )
                ),
                403,
            )
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("Origin")
            if origin is not None and not is_same_origin(origin, host_header):
                return (
                    jsonify(error="他のサイトからの変更操作は受け付けません(Origin が一致しません)"),
                    403,
                )
        return None
