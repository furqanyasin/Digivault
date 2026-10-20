"""One tag = one script row, whatever runtime state Google appends today.

`normalize_script_url` used to strip volatile query params by *denylist*. Google's
tag runtime keeps growing new ones (`cst`, `_slc`, `sst`, `pscdl`, `_ip`, `sess`,
`num`, `frm`, `z`…), and every unlisted param became part of the script's
identity. Two things followed, and they are the same bug seen from both ends:

  * one GA4 property listed as nine "files" on the Scripts tab, the same host
    repeated down the table;
  * a fresh `added` (and matching `removed`) ScriptChange every time Google
    rotated a param — an alert per rotation, per site, forever.

For a host whose script is identified entirely by a container/account id, the
identity params are a closed set. These tests pin the allowlist so a param
Google invents next quarter cannot split a tag again.
"""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.classifier import ScriptClassifier
from apps.scripts.models import Script, ScriptChange
from apps.scripts.normalize import normalize_script_url
from apps.scripts.tasks import process_ingest_payload
from apps.websites.models import Website


class TestGoogleTagIdentityIsTheContainerId:
    def test_unknown_runtime_params_do_not_split_a_container(self):
        """The exact leak: params absent from the denylist are not identity."""
        base = "https://www.googletagmanager.com/gtag/js?id=G-ABC123"
        variants = [
            base,
            base + "&l=dataLayer&cx=c",
            base + "&cst=1&gtm=45He51h1v9",
            base + "&_slc=1",
            base + "&sst=1&pscdl=noapi",
            base + "&_ip=1&tag_exp=101509157",
            base + "&sess=2&num=1&frm=0&z=91827364",
        ]
        assert len({normalize_script_url(u) for u in variants}) == 1

    def test_hardcoded_and_gtm_injected_loads_are_one_script(self):
        """The same property arrives both ways on one page; it is one tag."""
        hardcoded = normalize_script_url(
            "https://www.googletagmanager.com/gtag/js?id=G-ABC123"
        )
        injected = normalize_script_url(
            "https://www.googletagmanager.com/gtag/js?id=G-ABC123&l=dataLayer&cx=c"
        )
        assert hardcoded == injected

    def test_the_container_id_still_survives(self):
        assert "G-ABC123" in normalize_script_url(
            "https://www.googletagmanager.com/gtag/js?id=G-ABC123&cst=1&_slc=1"
        )

    def test_two_containers_never_merge(self):
        a = normalize_script_url("https://www.googletagmanager.com/gtm.js?id=GTM-AAA&sst=1")
        b = normalize_script_url("https://www.googletagmanager.com/gtm.js?id=GTM-BBB&sst=1")
        assert a != b

    def test_ga4_and_ads_on_one_host_stay_separate(self):
        ga4 = normalize_script_url("https://www.googletagmanager.com/gtag/js?id=G-ABC&_slc=1")
        ads = normalize_script_url("https://www.googletagmanager.com/gtag/js?id=AW-999&_slc=1")
        assert ga4 != ads

    def test_gtm_js_and_gtag_js_stay_separate(self):
        """Different endpoints on one host are different scripts."""
        assert normalize_script_url(
            "https://www.googletagmanager.com/gtm.js?id=GTM-ABC"
        ) != normalize_script_url(
            "https://www.googletagmanager.com/gtag/js?id=GTM-ABC"
        )

    def test_agency_google_urls_keep_ids_but_drop_runtime_query(self):
        urls = [
            "https://www.googletagmanager.com/gtag/js?id=G-0KTJ15QBB5&cx=c&gtm=4e6920h2",
            "https://www.googletagmanager.com/gtag/js?id=G-LC6FS8Y01E&cx=c&gtm=4e6911",
            "https://www.googletagmanager.com/gtm.js?id=GTM-NDF77KHJ&gtm=4e6920h2",
            "https://www.googletagmanager.com/gtm.js?id=GTM-N32TK6DJ&gtm=4e6911",
        ]
        normalized = [normalize_script_url(url) for url in urls]
        assert normalized == [
            "https://www.googletagmanager.com/gtag/js?id=G-0KTJ15QBB5",
            "https://www.googletagmanager.com/gtag/js?id=G-LC6FS8Y01E",
            "https://www.googletagmanager.com/gtm.js?id=GTM-NDF77KHJ",
            "https://www.googletagmanager.com/gtm.js?id=GTM-N32TK6DJ",
        ]

    def test_same_google_id_with_runtime_variants_is_one_identity(self):
        assert normalize_script_url(
            "https://www.googletagmanager.com/gtag/js?id=G-LC6FS8Y01E&cx=c&gtm=4e6911"
        ) == normalize_script_url(
            "https://www.googletagmanager.com/gtag/js?id=G-LC6FS8Y01E&cx=c&gtm=4e6920h2&cst=1"
        )


class TestOtherIdentityOnlyHosts:
    def test_recaptcha_site_key_is_identity(self):
        a = normalize_script_url("https://www.google.com/recaptcha/api.js?render=6LcKEY_ONE")
        b = normalize_script_url("https://www.google.com/recaptcha/api.js?render=6LcKEY_TWO")
        assert a != b
        assert "6LcKEY_ONE" in a

    def test_recaptcha_language_and_badge_are_not_identity(self):
        """One widget rendered in two locales is still one script."""
        a = normalize_script_url(
            "https://www.google.com/recaptcha/api.js?render=6LcKEY&hl=en&badge=inline"
        )
        b = normalize_script_url("https://www.google.com/recaptcha/api.js?render=6LcKEY")
        assert a == b

    def test_hotjar_script_version_is_not_identity(self):
        """`sv=` bumps on every Hotjar release; the account id is in the path."""
        a = normalize_script_url("https://static.hotjar.com/c/hotjar-3065386.js?sv=6")
        b = normalize_script_url("https://static.hotjar.com/c/hotjar-3065386.js?sv=7")
        assert a == b

    def test_hotjar_runtime_version_is_removed_from_identity(self):
        assert normalize_script_url(
            "https://script.hotjar.com/modules.e762be2b6b709245aabb.js?ver=0.20"
        ) == "https://script.hotjar.com/modules.js"

    def test_two_hotjar_accounts_stay_separate(self):
        a = normalize_script_url("https://static.hotjar.com/c/hotjar-3065386.js?sv=6")
        b = normalize_script_url("https://static.hotjar.com/c/hotjar-9999999.js?sv=6")
        assert a != b


class TestGtagDestinationIsNotUnknown:
    def test_destination_endpoint_is_attributed(self):
        """`/gtag/destination` fell through every pattern and read as an
        unnamed third party — its own row, flagged for review, on every site
        running Google Ads."""
        result = ScriptClassifier.classify(
            "https://www.googletagmanager.com/gtag/destination?id=AW-999&l=dataLayer"
        )
        assert result.provider != "unknown"


@pytest.mark.django_db
class TestRotationRaisesNoAlerts:
    """End to end: Google rotating its params must produce no news."""

    @pytest.fixture
    def website(self, db):
        owner = User.objects.create_user(email="tagid_o@test.com", password="Pass123!")
        team = TeamService.create(name="Tag Identity Agency", owner=owner)
        return Website.objects.create(team=team, name="Tag Site", domain="tagid.io")

    @staticmethod
    def _post(website, srcs):
        process_ingest_payload(
            str(website.site_id),
            {
                "page_url": "https://tagid.io/",
                "scripts": [
                    {
                        "src": s, "location": "head", "is_async": True,
                        "is_defer": False, "is_inline": False, "inline_hash": "",
                        "wp_plugin": "", "wp_post_id": None,
                    }
                    for s in srcs
                ],
            },
        )

    def test_param_rotation_yields_one_script_and_no_repeat_changes(self, website):
        gtm = "https://www.googletagmanager.com/gtm.js?id=GTM-ROT01"
        # The same GA4 property as Google re-shapes its src over a week.
        rotations = [
            "https://www.googletagmanager.com/gtag/js?id=G-ROT01&l=dataLayer&cx=c",
            "https://www.googletagmanager.com/gtag/js?id=G-ROT01&l=dataLayer&cx=c&cst=1",
            "https://www.googletagmanager.com/gtag/js?id=G-ROT01&_slc=1&sst=1",
            "https://www.googletagmanager.com/gtag/js?id=G-ROT01&pscdl=noapi&num=1",
            "https://www.googletagmanager.com/gtag/js?id=G-ROT01&_ip=1&frm=0&z=5512",
        ]
        for _ in range(2):
            for ga4 in rotations:
                self._post(website, [gtm, ga4])

        ga4_rows = Script.objects.filter(
            website=website, normalized_url__contains="gtag/js"
        )
        assert ga4_rows.count() == 1, [s.normalized_url for s in ga4_rows]

        # Each tag is announced exactly once, on its first sighting. Every
        # rotation after that is the same tag wearing a different query string,
        # and must be silent — that repeat is the daily alert nobody asked for.
        # Descriptions carry the tag id, so one site's four GA4 properties read
        # as four tags rather than as one event logged four times.
        added = ScriptChange.objects.filter(website=website, change_type="added")
        assert sorted(c.description for c in added) == [
            "New script added: Google Analytics 4 (G-ROT01)",
            "New script added: Google Tag Manager (GTM-ROT01)",
        ], [c.description for c in added]

        churn = ScriptChange.objects.filter(
            website=website, change_type__in=["removed", "url_changed"]
        )
        assert churn.count() == 0, [c.description for c in churn]


@pytest.mark.django_db
class TestExistingSplitRowsMerge:
    """Fixing normalization only helps new ingest — 0027 collapses what is there.

    A site that has been running for months already holds one Script row per
    param shape Google has used, and the review verdicts are spread across them.
    """

    @pytest.fixture
    def website(self, db):
        owner = User.objects.create_user(email="tagmerge_o@test.com", password="Pass123!")
        team = TeamService.create(name="Tag Merge Agency", owner=owner)
        return Website.objects.create(team=team, name="Merge Site", domain="tagmerge.io")

    def test_split_ga4_rows_collapse_and_keep_the_review_verdict(self, website):
        from apps.scripts.dedup import merge_duplicate_scripts

        shapes = [
            "https://www.googletagmanager.com/gtag/js?id=G-MERGE1&l=dataLayer&cx=c",
            "https://www.googletagmanager.com/gtag/js?id=G-MERGE1&cst=1",
            "https://www.googletagmanager.com/gtag/js?id=G-MERGE1&_slc=1&sst=1",
            "https://www.googletagmanager.com/gtag/js?id=G-MERGE1&pscdl=noapi",
        ]
        for i, src in enumerate(shapes):
            Script.objects.create(
                website=website,
                src_url=src,
                # The pre-fix identity: whatever the old denylist left behind.
                normalized_url=src,
                src_domain="www.googletagmanager.com",
                provider="Google Analytics 4",
                seen_on_pages=[f"https://tagmerge.io/page-{i}"],
                # Someone had already approved one of the four.
                review_status="approved" if i == 2 else "pending",
            )
        assert Script.objects.filter(website=website).count() == 4

        merge_duplicate_scripts(Script, ScriptChange)

        rows = Script.objects.filter(website=website)
        assert rows.count() == 1
        survivor = rows.get()
        # The approval is not thrown away by the merge.
        assert survivor.review_status == "approved"
        # Nor is the record of where the tag has been seen.
        assert len(set(survivor.seen_on_pages)) == 4
        assert survivor.normalized_url == (
            "https://www.googletagmanager.com/gtag/js?id=G-MERGE1"
        )
