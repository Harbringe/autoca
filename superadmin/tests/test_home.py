"""The platform owner's home page and the look of the admin: what the page shows, to whom, and that nothing third-party loads."""

from __future__ import annotations

import pytest

from api.tests.conftest import sign_in
from superadmin.tests.test_superadmin import (  # noqa: F401
    firm_a,
    firm_b,
    operator,
    views,
)

pytestmark = pytest.mark.django_db


def test_the_admin_loads_the_platform_stylesheet_and_no_third_party_fonts(views, operator):
    page = sign_in(operator).get("/admin/").content.decode()
    assert "superadmin/platform.css" in page
    assert "fonts.googleapis.com" not in page
