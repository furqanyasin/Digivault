import uuid

import pytest

from apps.common.models import BaseModel


class TestBaseModel:
    def test_pk_is_uuid(self):
        """Every concrete model built on BaseModel gets a UUID primary key."""
        pk_field = BaseModel._meta.get_field("id")
        assert pk_field.primary_key is True
        assert pk_field.__class__.__name__ == "UUIDField"
        assert pk_field.default is uuid.uuid4

    def test_has_created_at_field(self):
        field = BaseModel._meta.get_field("created_at")
        assert field.auto_now_add is True

    def test_has_updated_at_field(self):
        field = BaseModel._meta.get_field("updated_at")
        assert field.auto_now is True
