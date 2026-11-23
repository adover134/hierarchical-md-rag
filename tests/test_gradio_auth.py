"""Gradio 화면의 인증 설정(`scripts/gradio_app.py::resolve_auth`) 테스트 — 아이디·비밀번호는 환경변수(.env)에서만 읽는다."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from gradio_app import resolve_auth  # noqa: E402


def test_no_credentials_means_no_auth():
    assert resolve_auth({}) is None


def test_username_and_password_from_env():
    assert resolve_auth({"GRADIO_APP_USERNAME": "alice", "GRADIO_APP_PASSWORD": "pw"}) == ("alice", "pw")


def test_legacy_shared_password_name_is_still_read_as_password():
    assert resolve_auth({"GRADIO_APP_USERNAME": "alice", "GRADIO_APP_SHARED_PASSWORD": "pw"}) == ("alice", "pw")


def test_password_without_username_is_refused_instead_of_using_a_fixed_id():
    with pytest.raises(ValueError):
        resolve_auth({"GRADIO_APP_PASSWORD": "pw"})


def test_username_without_password_is_refused():
    with pytest.raises(ValueError):
        resolve_auth({"GRADIO_APP_USERNAME": "alice"})
