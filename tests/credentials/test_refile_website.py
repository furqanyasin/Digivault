"""A credential can be moved between the vault's two sections.

The vault splits "Website Credentials" from "Hosting & General" on
`Credential.website` alone — not on `credential_type`. Nothing could set that
field after creation: `CredentialWriteSerializer` accepted `website_id`, the
detail view read every other key out of `validated_data` and dropped that one,
and the request answered 200 having changed nothing. So every login saved
without a website was filed under Hosting permanently, which is how a vault of
233 credentials ends up with 229 in one section.

The `UNSET` sentinel is what makes the two intents expressible: `website` is
legitimately nullable, so "leave the link alone" and "unlink it" cannot both be
None.
"""

import pytest

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.credentials.models import Credential
from apps.credentials.services import CredentialService
from apps.websites.models import Website

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="refile_owner@test.com", password="SecurePass1!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Refile Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Refile Site", domain="refile.io")


@pytest.fixture
def hosting_credential(team, owner):
    """A login with no website — what the vault files under Hosting & General."""
    return CredentialService.create(
        label="Brickkicker Columbus",
        credential_type=Credential.CredentialType.CUSTOM,
        login_url="https://columbus.brickkicker.com/digihide",
        username="admin",
        password="Pass123!",
        notes="",
        created_by=owner,
        team=team,
    )


@pytest.fixture
def api(owner, team):
    from rest_framework.test import APIClient

    client = APIClient()
    response = client.post(
        "/api/v1/auth/token/",
        {"email": owner.email, "password": "SecurePass1!"},
        format="json",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return client


class TestServiceLayer:
    def test_omitting_website_leaves_the_link_alone(self, hosting_credential, website):
        hosting_credential.website = website
        hosting_credential.save(update_fields=["website"])

        CredentialService.update(credential=hosting_credential, label="Renamed")

        hosting_credential.refresh_from_db()
        assert hosting_credential.website_id == website.pk, (
            "a label edit unlinked the website"
        )

    def test_an_explicit_none_unlinks(self, hosting_credential, website):
        hosting_credential.website = website
        hosting_credential.save(update_fields=["website"])

        CredentialService.update(credential=hosting_credential, website=None)

        hosting_credential.refresh_from_db()
        assert hosting_credential.website_id is None

    def test_a_website_from_another_team_is_refused(self, hosting_credential, db):
        """The one mistake here that crosses a tenancy boundary."""
        other_owner = User.objects.create_user(
            email="refile_other@test.com", password="SecurePass1!"
        )
        other_team = TeamService.create(name="Other Agency", owner=other_owner)
        foreign = Website.objects.create(
            team=other_team, name="Foreign", domain="foreign.io"
        )

        with pytest.raises(ValueError):
            CredentialService.update(credential=hosting_credential, website=foreign)

        hosting_credential.refresh_from_db()
        assert hosting_credential.website_id is None


class TestEndpoint:
    def _patch(self, api, credential, body):
        return api.patch(
            f"/api/v1/credentials/{credential.id}/", body, format="json"
        )

    def test_moving_a_hosting_login_into_website_credentials(
        self, api, hosting_credential, website
    ):
        """The regression: this used to answer 200 and change nothing."""
        response = self._patch(api, hosting_credential, {"website_id": str(website.id)})

        assert response.status_code == 200, response.data
        hosting_credential.refresh_from_db()
        assert hosting_credential.website_id == website.pk
        # The section the vault will now render it in.
        assert response.data["website_id"] == str(website.id)
        assert response.data["website_name"] == website.name

    def test_moving_it_back_to_hosting(self, api, hosting_credential, website):
        hosting_credential.website = website
        hosting_credential.save(update_fields=["website"])

        response = self._patch(api, hosting_credential, {"website_id": None})

        assert response.status_code == 200, response.data
        hosting_credential.refresh_from_db()
        assert hosting_credential.website_id is None
        assert response.data["website_id"] is None

    def test_an_edit_that_does_not_mention_the_website_keeps_it(
        self, api, hosting_credential, website
    ):
        """Otherwise renaming a website login would silently re-file it."""
        hosting_credential.website = website
        hosting_credential.save(update_fields=["website"])

        response = self._patch(api, hosting_credential, {"label": "Renamed only"})

        assert response.status_code == 200, response.data
        hosting_credential.refresh_from_db()
        assert hosting_credential.label == "Renamed only"
        assert hosting_credential.website_id == website.pk

    def test_a_website_from_another_team_is_a_400_not_a_500(
        self, api, hosting_credential
    ):
        other_owner = User.objects.create_user(
            email="refile_other2@test.com", password="SecurePass1!"
        )
        other_team = TeamService.create(name="Other Agency 2", owner=other_owner)
        foreign = Website.objects.create(
            team=other_team, name="Foreign", domain="foreign2.io"
        )

        response = self._patch(api, hosting_credential, {"website_id": str(foreign.id)})

        assert response.status_code == 400
        hosting_credential.refresh_from_db()
        assert hosting_credential.website_id is None

    def test_an_unknown_website_id_is_refused_the_same_way(
        self, api, hosting_credential
    ):
        """Identical answer to the foreign-team case, so neither confirms the
        other's existence."""
        import uuid

        response = self._patch(
            api, hosting_credential, {"website_id": str(uuid.uuid4())}
        )
        assert response.status_code == 400
