from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """Standard paginator used across all list endpoints.

    Query params: ?page=1&page_size=25 (max 100)
    """

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        response = Response(data)
        response.meta = {
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
        }
        return response

    def get_paginated_response_schema(self, schema):
        return schema
