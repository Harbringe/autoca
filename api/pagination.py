"""Paging.

In its own module, and it has to be. Naming a pagination class that lives
alongside the view classes in ``DEFAULT_PAGINATION_CLASS`` is a circular import:
importing the views module pulls in ``rest_framework.viewsets``, which resolves
the setting, which imports the views module again -- mid-import, before the
class exists. The error DRF reports is "does not define a DefaultPagination
attribute", which describes the symptom and hides the cause.

So this module imports one thing from DRF, and nothing at all from the rest of
the project.
"""

from __future__ import annotations

from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """Fifty rows, because that is a screenful of a review queue.

    A statement is a few dozen rows and a client's year is a few hundred, so the
    cap exists to stop an accidental full-table fetch rather than because any
    real page is large.
    """

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500
