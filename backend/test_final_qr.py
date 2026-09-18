"""Superseded - Round 2 no longer has a "final QR"; the coordinator verifies the
Joker (spec section 20). That flow is covered by backend/tests/test_gameplay.py.

This file only remains so nothing breaks if it is invoked directly; it is
safe to delete.
"""
import pytest

pytest.skip("moved to backend/tests/", allow_module_level=True)
