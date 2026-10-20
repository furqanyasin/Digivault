# Digivault Core Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the complete Django backend foundation for Digivault — project structure, settings split, custom User/Team models with role-based access, JWT auth, OOP base classes, and Docker config — ready for feature apps to be bolted on.

**Architecture:** Monorepo Django project with a `config/` settings package, an `apps/` directory containing one Django app per feature domain, and a `common/` app housing all shared OOP base classes (BaseModel, TeamScopedQuerySet, RolePermission, envelope serializers). Every model carries a UUID pk and timestamps via an abstract base. Team isolation is enforced at the queryset level so no view can accidentally leak cross-team data.

**Tech Stack:** Python 3.12, Django 5.1, Django REST Framework 3.15, SimpleJWT, django-environ, psycopg2-binary, Redis, celery, django-redis, pytest-django, factory-boy, Fernet (cryptography library), Docker + docker-compose.

---

## File Map

```
scdb/
├── config/
│   ├── __init__.py
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py          # All shared settings
│   │   ├── development.py   # Overrides for local dev
│   │   └── production.py    # Secure production settings
│   ├── urls.py              # Root URL conf
│   ├── asgi.py              # ASGI entry (Channels-ready)
│   └── wsgi.py
├── apps/
│   ├── common/              # Shared OOP base classes — no models
│   │   ├── __init__.py
│   │   ├── models.py        # BaseModel abstract
│   │   ├── querysets.py     # TeamScopedQuerySet, SoftDeleteQuerySet
│   │   ├── mixins.py        # TeamScopedMixin, AuditMixin view mixins
│   │   ├── permissions.py   # RolePermission, IsTeamMember
│   │   ├── serializers.py   # BaseModelSerializer, EnvelopeSerializer
│   │   ├── renderers.py     # EnvelopeJSONRenderer
│   │   ├── pagination.py    # StandardPagination
│   │   ├── exceptions.py    # AppException hierarchy + DRF handler
│   │   └── apps.py
│   └── accounts/            # User, Team, membership, invitations
│       ├── __init__.py
│       ├── apps.py
│       ├── admin.py
│       ├── managers.py      # UserManager
│       ├── models.py        # User, Team, TeamMembership, TeamInvitation
│       ├── serializers.py   # Registration, login, team serializers
│       ├── services.py      # TeamService, InvitationService (business logic)
│       ├── views.py         # Auth + team API views
│       ├── urls.py
│       └── migrations/
│           └── __init__.py
├── tests/
│   ├── conftest.py          # Fixtures: db, user, team, api_client
│   ├── common/
│   │   ├── __init__.py
│   │   └── test_base_models.py
│   └── accounts/
│       ├── __init__.py
│       ├── test_models.py
│       ├── test_services.py
│       └── test_views.py
├── requirements/
│   ├── base.txt
│   ├── development.txt
│   └── production.txt
├── .env.example
├── manage.py
├── Dockerfile
├── docker-compose.yml
└── pytest.ini
```

---

## Task 1: Requirements Files and manage.py

**Files:**
- Create: `requirements/base.txt`
- Create: `requirements/development.txt`
- Create: `requirements/production.txt`
- Create: `manage.py`

- [ ] **Step 1: Create `requirements/base.txt`**

```text
Django==5.1.4
djangorestframework==3.15.2
djangorestframework-simplejwt==5.3.1
django-environ==0.11.2
django-cors-headers==4.4.0
django-redis==5.4.0
psycopg2-binary==2.9.9
celery==5.4.0
redis==5.1.0
cryptography==43.0.3
python-whois==0.9.4
Pillow==10.4.0
gunicorn==23.0.0
```

- [ ] **Step 2: Create `requirements/development.txt`**

```text
-r base.txt
pytest==8.3.3
pytest-django==4.9.0
pytest-cov==6.0.0
factory-boy==3.3.1
Faker==30.8.1
django-debug-toolbar==4.4.6
ipython==8.28.0
```

- [ ] **Step 3: Create `requirements/production.txt`**

```text
-r base.txt
sentry-sdk[django]==2.18.0
```

- [ ] **Step 4: Create `manage.py`**

```python
#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Commit**

```bash
git add requirements/ manage.py
git commit -m "chore: add requirements files and manage.py"
```

---

## Task 2: .env.example and Django Settings Split

**Files:**
- Create: `.env.example`
- Create: `config/__init__.py`
- Create: `config/settings/__init__.py`
- Create: `config/settings/base.py`
- Create: `config/settings/development.py`
- Create: `config/settings/production.py`
- Create: `config/urls.py`
- Create: `config/wsgi.py`
- Create: `config/asgi.py`

- [ ] **Step 1: Create `.env.example`**

```ini
# Copy to .env and fill in values
DJANGO_SECRET_KEY=replace-with-50-char-random-string
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DATABASE_URL=postgres://digivault:password@localhost:5432/digivault

# Redis
REDIS_URL=redis://localhost:6379/0

# Vault encryption key — generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
VAULT_ENCRYPTION_KEY=replace-with-fernet-key

# Email (development uses console backend)
EMAIL_URL=console://

# JWT
JWT_ACCESS_TOKEN_LIFETIME_MINUTES=15
JWT_REFRESH_TOKEN_LIFETIME_DAYS=7

# CORS
CORS_ALLOWED_ORIGINS=http://localhost:3000

# Sentry (production only)
SENTRY_DSN=
```

- [ ] **Step 2: Create `config/__init__.py`** (empty file)

```python
```

- [ ] **Step 3: Create `config/settings/__init__.py`** (empty file)

```python
```

- [ ] **Step 4: Create `config/settings/base.py`**

```python
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# ------------------------------------------------------------------
# Application definition
# ------------------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
]

LOCAL_APPS = [
    "apps.common",
    "apps.accounts",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ------------------------------------------------------------------
# Database
# ------------------------------------------------------------------

DATABASES = {"default": env.db("DATABASE_URL")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ------------------------------------------------------------------
# Cache — Redis
# ------------------------------------------------------------------

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/0"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        "KEY_PREFIX": "digivault",
    }
}

# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ------------------------------------------------------------------
# REST Framework
# ------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "apps.common.renderers.EnvelopeJSONRenderer",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/day",
        "user": "5000/day",
        "ingest": "10000/day",
    },
    "EXCEPTION_HANDLER": "apps.common.exceptions.custom_exception_handler",
}

# ------------------------------------------------------------------
# SimpleJWT
# ------------------------------------------------------------------

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=env.int("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", default=15)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=env.int("JWT_REFRESH_TOKEN_LIFETIME_DAYS", default=7)
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
}

# ------------------------------------------------------------------
# Celery
# ------------------------------------------------------------------

CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300  # 5 minutes hard limit per task

# ------------------------------------------------------------------
# Vault
# ------------------------------------------------------------------

VAULT_ENCRYPTION_KEY = env("VAULT_ENCRYPTION_KEY")

# ------------------------------------------------------------------
# Internationalisation
# ------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ------------------------------------------------------------------
# Static / Media
# ------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
```

- [ ] **Step 5: Create `config/settings/development.py`**

```python
from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405

MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]  # noqa: F405

INTERNAL_IPS = ["127.0.0.1"]

CORS_ALLOWED_ORIGINS = env.list(  # noqa: F405
    "CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"]
)

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
```

- [ ] **Step 6: Create `config/settings/production.py`**

```python
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

from .base import *  # noqa: F401, F403

DEBUG = False

# Security headers
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31_536_000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS")  # noqa: F405

# Sentry
sentry_sdk.init(
    dsn=env("SENTRY_DSN", default=""),  # noqa: F405
    integrations=[DjangoIntegration()],
    traces_sample_rate=0.1,
    send_default_pii=False,
)
```

- [ ] **Step 7: Create `config/urls.py`**

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.accounts.urls")),
]
```

- [ ] **Step 8: Create `config/wsgi.py`**

```python
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

application = get_wsgi_application()
```

- [ ] **Step 9: Create `config/asgi.py`**

```python
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

# Django Channels routing will be added here in a later phase
# when apps.alerts adds the WebSocket consumer.
application = get_asgi_application()
```

- [ ] **Step 10: Commit**

```bash
git add config/ .env.example
git commit -m "chore: add settings split, ASGI/WSGI config, and .env.example"
```

---

## Task 3: Common App — BaseModel and QuerySets

**Files:**
- Create: `apps/common/__init__.py`
- Create: `apps/common/apps.py`
- Create: `apps/common/models.py`
- Create: `apps/common/querysets.py`
- Create: `tests/common/__init__.py`
- Create: `tests/common/test_base_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/common/test_base_models.py
import uuid
import pytest
from apps.common.models import BaseModel


@pytest.mark.django_db
class TestBaseModel:
    def test_pk_is_uuid(self, db):
        """Every concrete model built on BaseModel gets a UUID primary key."""
        # Create a minimal concrete subclass via a test-only proxy
        # We test the abstract contract via the accounts.User model in task 5,
        # so here we just verify the field definition directly.
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
```

- [ ] **Step 2: Run test to confirm fail**

```bash
pytest tests/common/test_base_models.py -v
```
Expected: `ModuleNotFoundError: No module named 'apps'`

- [ ] **Step 3: Create `apps/common/__init__.py`** (empty)

```python
```

- [ ] **Step 4: Create `apps/common/apps.py`**

```python
from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"
    label = "common"
```

- [ ] **Step 5: Create `apps/common/models.py`**

```python
import uuid

from django.db import models


class BaseModel(models.Model):
    """Abstract base for every Digivault model.

    Provides UUID primary key, immutable created_at, and auto-updated updated_at.
    Never query this class directly — it is always subclassed.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]
```

- [ ] **Step 6: Create `apps/common/querysets.py`**

```python
from django.db import models


class TeamScopedQuerySet(models.QuerySet):
    """Mixin queryset that restricts results to a single team.

    Usage — on any model with a `team` FK:

        class Website(BaseModel):
            team = models.ForeignKey(Team, ...)
            objects = TeamScopedManager.from_queryset(TeamScopedQuerySet)()

        # In a view:
        Website.objects.for_team(request.user.active_team)
    """

    def for_team(self, team) -> "TeamScopedQuerySet":
        return self.filter(team=team)

    def for_user(self, user) -> "TeamScopedQuerySet":
        """Restrict to teams the user is a member of."""
        return self.filter(team__memberships__user=user)


class ActiveQuerySet(models.QuerySet):
    """Queryset that adds an `active()` filter for models with `is_active`."""

    def active(self) -> "ActiveQuerySet":
        return self.filter(is_active=True)

    def inactive(self) -> "ActiveQuerySet":
        return self.filter(is_active=False)
```

- [ ] **Step 7: Run tests again to verify pass**

```bash
pytest tests/common/test_base_models.py -v
```
Expected: `3 passed`

- [ ] **Step 8: Commit**

```bash
git add apps/common/ tests/common/
git commit -m "feat(common): add BaseModel with UUID pk and TeamScopedQuerySet"
```

---

## Task 4: Common App — Permissions, Exceptions, Renderer, Pagination, Serializers

**Files:**
- Create: `apps/common/permissions.py`
- Create: `apps/common/exceptions.py`
- Create: `apps/common/renderers.py`
- Create: `apps/common/pagination.py`
- Create: `apps/common/serializers.py`
- Create: `apps/common/mixins.py`

- [ ] **Step 1: Create `apps/common/exceptions.py`**

```python
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler


class AppError(APIException):
    """Base exception for all Digivault domain errors.

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


def custom_exception_handler(exc, context):
    """Wrap DRF's default exception handler output in the standard envelope."""
    response = exception_handler(exc, context)

    if response is not None:
        code = getattr(exc, "default_code", "error")
        response.data = {
            "data": None,
            "errors": [{"code": code, "message": str(exc.detail)}],
            "meta": {},
        }

    return response
```

- [ ] **Step 2: Create `apps/common/renderers.py`**

```python
import json

from rest_framework.renderers import JSONRenderer


class EnvelopeJSONRenderer(JSONRenderer):
    """Wraps every API response in {data, errors, meta} envelope.

    Views that need to customise meta can set `response.meta` on the
    Response object before returning it.
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = renderer_context.get("response") if renderer_context else None
        meta = getattr(response, "meta", {})

        # Already wrapped by the exception handler — pass through
        if isinstance(data, dict) and "errors" in data and "data" in data:
            return super().render(data, accepted_media_type, renderer_context)

        envelope = {
            "data": data,
            "errors": [],
            "meta": meta,
        }
        return super().render(envelope, accepted_media_type, renderer_context)
```

- [ ] **Step 3: Create `apps/common/pagination.py`**

```python
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
```

- [ ] **Step 4: Create `apps/common/serializers.py`**

```python
from rest_framework import serializers


class BaseModelSerializer(serializers.ModelSerializer):
    """Base serializer that always includes id, created_at, updated_at as read-only."""

    class Meta:
        read_only_fields = ("id", "created_at", "updated_at")
```

- [ ] **Step 5: Create `apps/common/permissions.py`**

```python
from rest_framework.permissions import BasePermission

from apps.accounts.models import TeamMembership


class IsTeamMember(BasePermission):
    """Grants access to any authenticated user who is a member of the team
    identified by the `team_pk` URL kwarg or the user's active team."""

    message = "You are not a member of this team."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        team_pk = view.kwargs.get("team_pk")
        if team_pk:
            return TeamMembership.objects.filter(
                user=request.user, team_id=team_pk
            ).exists()
        return request.user.active_team is not None


class RolePermission(BasePermission):
    """Enforce minimum team role.

    Set `required_role` on the view class to the minimum role string.
    Role hierarchy (ascending privilege): viewer < developer < manager < owner
    """

    ROLE_LEVELS = {
        "viewer": 1,
        "developer": 2,
        "manager": 3,
        "owner": 4,
    }

    required_role: str = "viewer"

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        required = self.ROLE_LEVELS.get(getattr(view, "required_role", "viewer"), 1)
        team = request.user.active_team
        if team is None:
            return False

        try:
            membership = TeamMembership.objects.get(user=request.user, team=team)
        except TeamMembership.DoesNotExist:
            return False

        actual = self.ROLE_LEVELS.get(membership.role, 0)
        return actual >= required
```

- [ ] **Step 6: Create `apps/common/mixins.py`**

```python
class TeamScopedMixin:
    """View mixin that injects the authenticated user's active team into every
    queryset call, providing defence-in-depth data isolation.

    The model's manager must expose `.for_team(team)` (via TeamScopedQuerySet).
    """

    def get_queryset(self):
        qs = super().get_queryset()
        team = self.request.user.active_team
        if team is None:
            return qs.none()
        return qs.for_team(team)
```

- [ ] **Step 7: Commit**

```bash
git add apps/common/
git commit -m "feat(common): add permissions, exceptions, renderer, pagination, serializers, mixins"
```

---

## Task 5: Accounts App — User Model and Manager

**Files:**
- Create: `apps/accounts/__init__.py`
- Create: `apps/accounts/apps.py`
- Create: `apps/accounts/managers.py`
- Create: `apps/accounts/models.py` (partial — User only, Team added in Task 6)
- Create: `apps/accounts/migrations/__init__.py`
- Create: `tests/accounts/__init__.py`
- Create: `tests/accounts/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/accounts/test_models.py
import pytest
from apps.accounts.models import User


@pytest.mark.django_db
class TestUserModel:
    def test_create_user_sets_email_as_username(self):
        user = User.objects.create_user(
            email="alice@example.com", password="TestPass123!"
        )
        assert user.email == "alice@example.com"
        assert user.username == "alice@example.com"

    def test_create_user_password_is_hashed(self):
        user = User.objects.create_user(
            email="bob@example.com", password="TestPass123!"
        )
        assert user.check_password("TestPass123!")
        assert not user.check_password("WrongPassword")

    def test_create_superuser(self):
        user = User.objects.create_superuser(
            email="admin@example.com", password="AdminPass123!"
        )
        assert user.is_staff
        assert user.is_superuser

    def test_pk_is_uuid(self):
        user = User.objects.create_user(
            email="uuid@example.com", password="TestPass123!"
        )
        import uuid
        assert isinstance(user.pk, uuid.UUID)

    def test_str_returns_email(self):
        user = User.objects.create_user(
            email="str@example.com", password="TestPass123!"
        )
        assert str(user) == "str@example.com"
```

- [ ] **Step 2: Run test to confirm fail**

```bash
pytest tests/accounts/test_models.py -v
```
Expected: `ModuleNotFoundError` or `ImproperlyConfigured` (AUTH_USER_MODEL not yet resolved)

- [ ] **Step 3: Create `apps/accounts/__init__.py`** (empty)

```python
```

- [ ] **Step 4: Create `apps/accounts/apps.py`**

```python
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
```

- [ ] **Step 5: Create `apps/accounts/migrations/__init__.py`** (empty)

```python
```

- [ ] **Step 6: Create `apps/accounts/managers.py`**

```python
from django.contrib.auth.models import BaseUserManager


class UserManager(BaseUserManager):
    """Custom manager that treats email as the unique identifier instead of username."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str, **extra_fields):
        if not email:
            raise ValueError("Email address is required.")
        email = self.normalize_email(email)
        # Keep username in sync with email so Django internals stay happy
        extra_fields.setdefault("username", email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)
```

- [ ] **Step 7: Create `apps/accounts/models.py`** (User only — Team is added in Task 6)

```python
import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.accounts.managers import UserManager
from apps.common.models import BaseModel


class User(AbstractUser):
    """Custom user model.  Email is the login identifier; username mirrors it.

    Extends AbstractUser so Django's auth plumbing (permissions, admin) works
    out of the box. The UUID pk is inherited from AbstractUser override below.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    # username kept for Django internals but never shown in the UI
    username = models.CharField(max_length=254, unique=True)

    profile_photo = models.ImageField(
        upload_to="profiles/", null=True, blank=True
    )
    timezone = models.CharField(max_length=50, default="UTC")

    # The team the user is currently "acting as" — set at login or team switch.
    # Nullable because a freshly registered user has no team yet.
    active_team = models.ForeignKey(
        "accounts.Team",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # email is already required by USERNAME_FIELD

    objects = UserManager()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email
```

- [ ] **Step 8: Create initial migration**

```bash
python manage.py makemigrations accounts
```
Expected output: `Migrations for 'accounts': apps/accounts/migrations/0001_initial.py`

- [ ] **Step 9: Run tests**

```bash
pytest tests/accounts/test_models.py -v
```
Expected: `5 passed`

- [ ] **Step 10: Commit**

```bash
git add apps/accounts/ tests/accounts/test_models.py
git commit -m "feat(accounts): add custom User model with UUID pk and email login"
```

---

## Task 6: Accounts App — Team, TeamMembership, TeamInvitation Models

**Files:**
- Modify: `apps/accounts/models.py`
- Modify: `tests/accounts/test_models.py`

- [ ] **Step 1: Add team model tests**

Append to `tests/accounts/test_models.py`:

```python
from apps.accounts.models import Team, TeamMembership, TeamInvitation


@pytest.mark.django_db
class TestTeamModel:
    def test_team_creation(self):
        owner = User.objects.create_user(email="owner@acme.com", password="Pass123!")
        team = Team.objects.create(name="Acme Agency", owner=owner)
        assert str(team) == "Acme Agency"
        assert team.slug  # auto-generated

    def test_slug_is_unique(self):
        owner = User.objects.create_user(email="o1@acme.com", password="Pass123!")
        owner2 = User.objects.create_user(email="o2@acme.com", password="Pass123!")
        t1 = Team.objects.create(name="Acme", owner=owner)
        t2 = Team.objects.create(name="Acme", owner=owner2)
        assert t1.slug != t2.slug


@pytest.mark.django_db
class TestTeamMembership:
    def test_owner_membership_created_on_team_save(self):
        owner = User.objects.create_user(email="owner@test.com", password="Pass123!")
        team = Team.objects.create(name="Test Agency", owner=owner)
        assert TeamMembership.objects.filter(
            user=owner, team=team, role=TeamMembership.Role.OWNER
        ).exists()

    def test_role_choices(self):
        roles = [r.value for r in TeamMembership.Role]
        assert set(roles) == {"owner", "manager", "developer", "viewer"}
```

- [ ] **Step 2: Run new tests to confirm fail**

```bash
pytest tests/accounts/test_models.py -v
```
Expected: `ImportError: cannot import name 'Team'`

- [ ] **Step 3: Add Team, TeamMembership, TeamInvitation to `apps/accounts/models.py`**

Append after the `User` class:

```python
import secrets

from django.utils.text import slugify


class Team(BaseModel):
    """Represents a web agency or freelancer account.

    A user can be a member of multiple teams but has exactly one active_team at
    a time. All client data (websites, scripts, credentials) is scoped to a team.
    """

    class Plan(models.TextChoices):
        STARTER = "starter", "Starter"
        AGENCY = "agency", "Agency"
        AGENCY_PRO = "agency_pro", "Agency Pro"
        ENTERPRISE = "enterprise", "Enterprise"

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    owner = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="owned_teams",
    )
    plan = models.CharField(
        max_length=20, choices=Plan.choices, default=Plan.STARTER
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)
        # Ensure owner always has an owner-level membership
        TeamMembership.objects.get_or_create(
            user=self.owner,
            team=self,
            defaults={"role": TeamMembership.Role.OWNER},
        )

    def _generate_unique_slug(self) -> str:
        base = slugify(self.name)
        slug = base
        counter = 1
        while Team.objects.filter(slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        return slug


class TeamMembership(BaseModel):
    """Links a User to a Team with an assigned role."""

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MANAGER = "manager", "Manager"
        DEVELOPER = "developer", "Developer"
        VIEWER = "viewer", "Viewer"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="memberships"
    )
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.DEVELOPER
    )

    class Meta:
        unique_together = [("user", "team")]
        ordering = ["team", "role"]

    def __str__(self) -> str:
        return f"{self.user.email} — {self.team.name} ({self.role})"


class TeamInvitation(BaseModel):
    """Pending email invitation to join a team."""

    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="invitations"
    )
    invited_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="sent_invitations"
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=20,
        choices=TeamMembership.Role.choices,
        default=TeamMembership.Role.DEVELOPER,
    )
    token = models.CharField(max_length=64, unique=True, blank=True)
    accepted = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("team", "email")]
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(48)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Invitation for {self.email} to {self.team.name}"
```

- [ ] **Step 4: Run migrations**

```bash
python manage.py makemigrations accounts
python manage.py migrate
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/accounts/test_models.py -v
```
Expected: `9 passed`

- [ ] **Step 6: Commit**

```bash
git add apps/accounts/models.py tests/accounts/test_models.py apps/accounts/migrations/
git commit -m "feat(accounts): add Team, TeamMembership, TeamInvitation models"
```

---

## Task 7: Accounts App — Services Layer

**Files:**
- Create: `apps/accounts/services.py`
- Create: `tests/accounts/test_services.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/accounts/test_services.py
import pytest
from apps.accounts.models import User, Team, TeamMembership, TeamInvitation
from apps.accounts.services import TeamService, InvitationService
from apps.common.exceptions import ConflictError, NotFoundError, ForbiddenError


@pytest.mark.django_db
class TestTeamService:
    def test_create_team_sets_active_team_on_owner(self):
        owner = User.objects.create_user(email="owner@svc.com", password="Pass123!")
        team = TeamService.create(name="My Agency", owner=owner)
        owner.refresh_from_db()
        assert owner.active_team == team

    def test_add_member_creates_membership(self):
        owner = User.objects.create_user(email="o@svc.com", password="Pass123!")
        member = User.objects.create_user(email="m@svc.com", password="Pass123!")
        team = TeamService.create(name="Agency A", owner=owner)
        membership = TeamService.add_member(
            team=team, user=member, role=TeamMembership.Role.DEVELOPER
        )
        assert membership.role == TeamMembership.Role.DEVELOPER

    def test_add_member_duplicate_raises_conflict(self):
        owner = User.objects.create_user(email="dup@svc.com", password="Pass123!")
        member = User.objects.create_user(email="dup2@svc.com", password="Pass123!")
        team = TeamService.create(name="Agency B", owner=owner)
        TeamService.add_member(team=team, user=member, role=TeamMembership.Role.VIEWER)
        with pytest.raises(ConflictError):
            TeamService.add_member(
                team=team, user=member, role=TeamMembership.Role.VIEWER
            )

    def test_remove_owner_raises_forbidden(self):
        owner = User.objects.create_user(email="rem@svc.com", password="Pass123!")
        team = TeamService.create(name="Agency C", owner=owner)
        with pytest.raises(ForbiddenError):
            TeamService.remove_member(team=team, user=owner)


@pytest.mark.django_db
class TestInvitationService:
    def test_create_invitation_generates_token(self):
        owner = User.objects.create_user(email="inv_o@svc.com", password="Pass123!")
        team = TeamService.create(name="Invite Agency", owner=owner)
        invitation = InvitationService.invite(
            team=team,
            invited_by=owner,
            email="newmember@client.com",
            role=TeamMembership.Role.DEVELOPER,
        )
        assert len(invitation.token) > 20

    def test_accept_invitation_creates_membership(self):
        owner = User.objects.create_user(email="acc_o@svc.com", password="Pass123!")
        new_user = User.objects.create_user(
            email="acc_m@svc.com", password="Pass123!"
        )
        team = TeamService.create(name="Accept Agency", owner=owner)
        invitation = InvitationService.invite(
            team=team,
            invited_by=owner,
            email=new_user.email,
            role=TeamMembership.Role.DEVELOPER,
        )
        InvitationService.accept(token=invitation.token, user=new_user)
        assert TeamMembership.objects.filter(user=new_user, team=team).exists()
```

- [ ] **Step 2: Run tests to confirm fail**

```bash
pytest tests/accounts/test_services.py -v
```
Expected: `ImportError: cannot import name 'TeamService'`

- [ ] **Step 3: Create `apps/accounts/services.py`**

```python
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Team, TeamInvitation, TeamMembership, User
from apps.common.exceptions import ConflictError, ForbiddenError, NotFoundError


class TeamService:
    """All business logic for team lifecycle management.

    Views should call these methods rather than touching models directly.
    This keeps validation and side-effects in one place.
    """

    @staticmethod
    @transaction.atomic
    def create(name: str, owner: User) -> Team:
        """Create a team and set it as the owner's active team."""
        team = Team.objects.create(name=name, owner=owner)
        owner.active_team = team
        owner.save(update_fields=["active_team"])
        return team

    @staticmethod
    @transaction.atomic
    def add_member(
        team: Team, user: User, role: str = TeamMembership.Role.DEVELOPER
    ) -> TeamMembership:
        if TeamMembership.objects.filter(team=team, user=user).exists():
            raise ConflictError(
                f"{user.email} is already a member of {team.name}."
            )
        return TeamMembership.objects.create(team=team, user=user, role=role)

    @staticmethod
    @transaction.atomic
    def remove_member(team: Team, user: User) -> None:
        if user == team.owner:
            raise ForbiddenError("The team owner cannot be removed from the team.")
        deleted, _ = TeamMembership.objects.filter(team=team, user=user).delete()
        if not deleted:
            raise NotFoundError(f"{user.email} is not a member of {team.name}.")

    @staticmethod
    @transaction.atomic
    def update_member_role(team: Team, user: User, role: str) -> TeamMembership:
        if user == team.owner:
            raise ForbiddenError("Cannot change the owner's role.")
        try:
            membership = TeamMembership.objects.get(team=team, user=user)
        except TeamMembership.DoesNotExist:
            raise NotFoundError(f"{user.email} is not a member of {team.name}.")
        membership.role = role
        membership.save(update_fields=["role", "updated_at"])
        return membership


class InvitationService:
    """Business logic for team invitations."""

    @staticmethod
    @transaction.atomic
    def invite(
        team: Team,
        invited_by: User,
        email: str,
        role: str = TeamMembership.Role.DEVELOPER,
    ) -> TeamInvitation:
        if TeamMembership.objects.filter(team=team, user__email=email).exists():
            raise ConflictError(f"{email} is already a member of {team.name}.")
        invitation, created = TeamInvitation.objects.get_or_create(
            team=team,
            email=email,
            defaults={"invited_by": invited_by, "role": role},
        )
        if not created and invitation.accepted:
            raise ConflictError(f"{email} has already accepted an invitation.")
        return invitation

    @staticmethod
    @transaction.atomic
    def accept(token: str, user: User) -> TeamMembership:
        try:
            invitation = TeamInvitation.objects.select_for_update().get(
                token=token, accepted=False
            )
        except TeamInvitation.DoesNotExist:
            raise NotFoundError("Invitation not found or already accepted.")

        if invitation.email != user.email:
            raise ForbiddenError("This invitation was sent to a different email address.")

        membership = TeamService.add_member(
            team=invitation.team, user=user, role=invitation.role
        )
        invitation.accepted = True
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted", "accepted_at"])

        if user.active_team is None:
            user.active_team = invitation.team
            user.save(update_fields=["active_team"])

        return membership
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/accounts/test_services.py -v
```
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add apps/accounts/services.py tests/accounts/test_services.py
git commit -m "feat(accounts): add TeamService and InvitationService"
```

---

## Task 8: Accounts App — Serializers and Auth Views

**Files:**
- Create: `apps/accounts/serializers.py`
- Create: `apps/accounts/views.py`
- Create: `apps/accounts/urls.py`
- Create: `tests/accounts/test_views.py`

- [ ] **Step 1: Write the failing view tests**

```python
# tests/accounts/test_views.py
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User, Team, TeamMembership
from apps.accounts.services import TeamService


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def registered_user(db):
    return User.objects.create_user(email="test@example.com", password="SecurePass1!")


@pytest.fixture
def auth_client(registered_user):
    client = APIClient()
    response = client.post(
        "/api/v1/auth/token/",
        {"email": "test@example.com", "password": "SecurePass1!"},
        format="json",
    )
    token = response.data["data"]["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db
class TestRegistration:
    def test_register_creates_user(self, api_client):
        response = api_client.post(
            "/api/v1/auth/register/",
            {"email": "new@user.com", "password": "SecurePass1!", "name": "New User"},
            format="json",
        )
        assert response.status_code == 201
        assert User.objects.filter(email="new@user.com").exists()

    def test_duplicate_email_returns_400(self, api_client, registered_user):
        response = api_client.post(
            "/api/v1/auth/register/",
            {
                "email": "test@example.com",
                "password": "SecurePass1!",
                "name": "Dupe",
            },
            format="json",
        )
        assert response.status_code == 400

    def test_weak_password_returns_400(self, api_client):
        response = api_client.post(
            "/api/v1/auth/register/",
            {"email": "weak@pass.com", "password": "123", "name": "Weak"},
            format="json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestTokenObtain:
    def test_valid_credentials_return_tokens(self, api_client, registered_user):
        response = api_client.post(
            "/api/v1/auth/token/",
            {"email": "test@example.com", "password": "SecurePass1!"},
            format="json",
        )
        assert response.status_code == 200
        assert "access" in response.data["data"]
        assert "refresh" in response.data["data"]

    def test_invalid_password_returns_401(self, api_client, registered_user):
        response = api_client.post(
            "/api/v1/auth/token/",
            {"email": "test@example.com", "password": "WrongPass"},
            format="json",
        )
        assert response.status_code == 401


@pytest.mark.django_db
class TestTeamAPI:
    def test_create_team(self, auth_client):
        response = auth_client.post(
            "/api/v1/auth/teams/",
            {"name": "My Agency"},
            format="json",
        )
        assert response.status_code == 201
        assert response.data["data"]["name"] == "My Agency"

    def test_list_teams_returns_only_user_teams(self, auth_client, registered_user):
        TeamService.create(name="My Team", owner=registered_user)
        other_owner = User.objects.create_user(
            email="other@example.com", password="Pass1234!"
        )
        TeamService.create(name="Other Team", owner=other_owner)
        response = auth_client.get("/api/v1/auth/teams/")
        names = [t["name"] for t in response.data["data"]]
        assert "My Team" in names
        assert "Other Team" not in names
```

- [ ] **Step 2: Run tests to confirm fail**

```bash
pytest tests/accounts/test_views.py -v
```
Expected: fail with connection/URL errors

- [ ] **Step 3: Create `apps/accounts/serializers.py`**

```python
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from apps.accounts.models import Team, TeamInvitation, TeamMembership, User
from apps.common.serializers import BaseModelSerializer


class UserRegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField(
        validators=[UniqueValidator(queryset=User.objects.all())]
    )
    password = serializers.CharField(write_only=True, min_length=8)
    name = serializers.CharField(max_length=150)

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        name = validated_data.pop("name", "")
        first, *rest = name.split(" ", 1)
        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=first,
            last_name=rest[0] if rest else "",
        )
        return user


class UserSerializer(BaseModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name", "timezone", "created_at")
        read_only_fields = ("id", "email", "created_at")


class TeamSerializer(BaseModelSerializer):
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = ("id", "name", "slug", "plan", "member_count", "created_at")
        read_only_fields = ("id", "slug", "created_at")

    def get_member_count(self, obj) -> int:
        return obj.memberships.count()


class TeamMembershipSerializer(BaseModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = TeamMembership
        fields = ("id", "user", "role", "created_at")
        read_only_fields = ("id", "created_at")


class TeamInvitationSerializer(BaseModelSerializer):
    class Meta:
        model = TeamInvitation
        fields = ("id", "email", "role", "accepted", "created_at")
        read_only_fields = ("id", "accepted", "created_at")
```

- [ ] **Step 4: Create `apps/accounts/views.py`**

```python
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.models import Team, TeamMembership
from apps.accounts.serializers import (
    TeamMembershipSerializer,
    TeamSerializer,
    UserRegistrationSerializer,
    UserSerializer,
)
from apps.accounts.services import TeamService
from apps.common.mixins import TeamScopedMixin
from apps.common.permissions import IsTeamMember, RolePermission


class RegisterView(APIView):
    """POST /api/v1/auth/register/ — create a new user account."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class TeamListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/auth/teams/ — list the user's teams or create a new one."""

    serializer_class = TeamSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Team.objects.filter(
            memberships__user=self.request.user
        ).prefetch_related("memberships")

    def perform_create(self, serializer):
        TeamService.create(
            name=serializer.validated_data["name"],
            owner=self.request.user,
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        team = TeamService.create(
            name=serializer.validated_data["name"], owner=request.user
        )
        return Response(
            TeamSerializer(team).data, status=status.HTTP_201_CREATED
        )


class TeamDetailView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/auth/teams/<pk>/ — retrieve or update a team."""

    serializer_class = TeamSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        return Team.objects.filter(memberships__user=self.request.user)


class TeamMemberListView(generics.ListAPIView):
    """GET /api/v1/auth/teams/<team_pk>/members/ — list team members."""

    serializer_class = TeamMembershipSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        return TeamMembership.objects.filter(
            team_id=self.kwargs["team_pk"],
            team__memberships__user=self.request.user,
        ).select_related("user")


class MeView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/auth/me/ — current user profile."""

    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user
```

- [ ] **Step 5: Create `apps/accounts/urls.py`**

```python
from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.views import (
    MeView,
    RegisterView,
    TeamDetailView,
    TeamListCreateView,
    TeamMemberListView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("token/", TokenObtainPairView.as_view(), name="auth-token-obtain"),
    path("token/refresh/", TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("teams/", TeamListCreateView.as_view(), name="team-list-create"),
    path("teams/<uuid:pk>/", TeamDetailView.as_view(), name="team-detail"),
    path(
        "teams/<uuid:team_pk>/members/",
        TeamMemberListView.as_view(),
        name="team-members",
    ),
]
```

- [ ] **Step 6: Run all tests**

```bash
pytest tests/ -v
```
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add apps/accounts/ tests/accounts/test_views.py
git commit -m "feat(accounts): add auth and team management API endpoints"
```

---

## Task 9: Test Configuration and conftest

**Files:**
- Create: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pytest.ini`**

```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings.development
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = --reuse-db -p no:warnings
```

- [ ] **Step 2: Create `tests/__init__.py`** (empty)

```python
```

- [ ] **Step 3: Create `tests/conftest.py`**

```python
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Team, TeamMembership, User
from apps.accounts.services import TeamService


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="fixture@example.com", password="SecurePass1!"
    )


@pytest.fixture
def team(user):
    return TeamService.create(name="Fixture Agency", owner=user)


@pytest.fixture
def auth_client(user, team):
    client = APIClient()
    response = client.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "SecurePass1!"},
        format="json",
    )
    token = response.data["data"]["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def developer_user(db, team):
    dev = User.objects.create_user(email="dev@example.com", password="SecurePass1!")
    TeamMembership.objects.create(
        user=dev, team=team, role=TeamMembership.Role.DEVELOPER
    )
    return dev
```

- [ ] **Step 4: Run the full suite with coverage**

```bash
pytest tests/ -v --cov=apps --cov-report=term-missing
```
Expected: all pass, coverage visible

- [ ] **Step 5: Commit**

```bash
git add pytest.ini tests/conftest.py tests/__init__.py
git commit -m "chore: configure pytest with shared fixtures"
```

---

## Task 10: Docker and docker-compose

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `apps/__init__.py`

- [ ] **Step 1: Create `apps/__init__.py`** (empty)

```python
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/base.txt requirements/base.txt
COPY requirements/production.txt requirements/production.txt
RUN pip install -r requirements/production.txt

COPY . .

RUN python manage.py collectstatic --noinput \
    --settings=config.settings.production || true

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
version: "3.9"

services:
  db:
    image: postgres:16-alpine
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: scriptsentry
      POSTGRES_USER: scriptsentry
      POSTGRES_PASSWORD: password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U scriptsentry"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  api:
    build: .
    command: >
      sh -c "python manage.py migrate --settings=config.settings.development &&
             python manage.py runserver 0.0.0.0:8000 --settings=config.settings.development"
    volumes:
      - .:/app
    ports:
      - "8000:8000"
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.development
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy

  celery:
    build: .
    command: celery -A config worker -l info
    volumes:
      - .:/app
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy

  celery-beat:
    build: .
    command: celery -A config beat -l info
    volumes:
      - .:/app
    env_file:
      - .env
    depends_on:
      - redis

volumes:
  postgres_data:
```

- [ ] **Step 4: Verify Docker build (optional — skippable on first run)**

```bash
docker-compose build
```
Expected: successful build

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml apps/__init__.py
git commit -m "chore: add Dockerfile and docker-compose for local dev"
```

---

## Task 11: Accounts Admin Registration

**Files:**
- Create: `apps/accounts/admin.py`

- [ ] **Step 1: Create `apps/accounts/admin.py`**

```python
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import Team, TeamInvitation, TeamMembership, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "first_name", "last_name", "is_staff", "created_at")
    list_filter = ("is_staff", "is_superuser", "is_active")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "timezone", "profile_photo")}),
        ("Team", {"fields": ("active_team",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "password1", "password2"),
        }),
    )


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner", "plan", "created_at")
    search_fields = ("name", "slug", "owner__email")
    list_filter = ("plan",)
    raw_id_fields = ("owner",)


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "team", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("user__email", "team__name")


@admin.register(TeamInvitation)
class TeamInvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "team", "role", "accepted", "created_at")
    list_filter = ("accepted", "role")
    search_fields = ("email", "team__name")
```

- [ ] **Step 2: Run full test suite to confirm no regressions**

```bash
pytest tests/ -v
```
Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add apps/accounts/admin.py
git commit -m "feat(accounts): register models in Django admin"
```

---

## Self-Review

### Spec Coverage Check

| Spec Requirement | Task Covering It |
|---|---|
| Django 5.1, Python 3.12 | Task 1 (requirements) |
| Settings split base/dev/prod | Task 2 |
| UUID primary keys on all models | Tasks 3, 5 |
| AbstractUser with email login | Task 5 |
| Team, TeamMembership (4 roles), TeamInvitation | Task 6 |
| JWT 15-min access / 7-day refresh | Task 2 (SIMPLE_JWT config) |
| HttpOnly refresh cookie | SimpleJWT handles this; wiring to cookie done in Phase 2 |
| REST envelope {data, errors, meta} | Task 4 |
| Custom exception handler | Task 4 |
| TeamScopedQuerySet for data isolation | Task 3 |
| RolePermission enforced at API level | Task 4 |
| Standard pagination | Task 4 |
| Rate limiting | Task 2 (REST_FRAMEWORK throttle config) |
| Redis cache backend | Task 2 (CACHES config) |
| Celery config | Task 2 |
| Docker + docker-compose | Task 10 |
| Admin registration | Task 11 |

### Gap: Celery App entry point

The `docker-compose.yml` references `celery -A config worker` but `config/celery.py` is not yet created.

- [ ] **Fix: Create `config/celery.py`**

```python
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("digivault")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

Update `config/__init__.py` to load the Celery app at Django startup:

```python
from .celery import app as celery_app

__all__ = ["celery_app"]
```

Commit:
```bash
git add config/celery.py config/__init__.py
git commit -m "chore: add Celery application entry point"
```

---

*End of Core Foundation Plan*
