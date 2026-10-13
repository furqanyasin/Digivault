from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler


class AppError(APIException):
    """Base exception for all Stacks Monitor domain errors.

    Subclass this to create typed errors that map to specific HTTP status codes.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "error"
    default_detail = "An error occurred."


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "not_found"
    default_detail = "The requested resource was not found."


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "forbidden"
    default_detail = "You do not have permission to perform this action."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"
    default_detail = "A conflict occurred with the current state."


def _flatten_errors(detail):
    """Recursively flatten DRF validation error detail into a list of (code, message) tuples."""
    errors = []
    if isinstance(detail, dict):
        for field, value in detail.items():
            for code, msg in _flatten_errors(value):
                label = f"{field}: {msg}" if field != "non_field_errors" else msg
                errors.append((code, label))
    elif isinstance(detail, list):
        for item in detail:
            errors.extend(_flatten_errors(item))
    else:
        code = getattr(detail, "code", "invalid")
        errors.append((code, str(detail)))
    return errors


def custom_exception_handler(exc, context):
    """Wrap DRF's default exception handler output in the standard envelope."""
    response = exception_handler(exc, context)

    if response is not None:
        detail = exc.detail if hasattr(exc, "detail") else str(exc)
        flat = _flatten_errors(detail)
        if flat:
            errors = [{"code": code, "message": msg} for code, msg in flat]
        else:
            code = getattr(exc, "default_code", "error")
            errors = [{"code": code, "message": str(detail)}]
        response.data = {"data": None, "errors": errors, "meta": {}}

    return response
