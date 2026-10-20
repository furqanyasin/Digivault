# Credential sub-teams (Groups)

**Date:** 2026-09-02
**Status:** Approved, not yet implemented
**Scope:** Backend (`apps/accounts`, `apps/credentials`) + frontend (team page, credentials page) + two pre-existing security fixes in the reveal path.

## Problem

Credential access today has exactly two shapes (`CredentialQuerySet.visible_to`
in `apps/credentials/models.py`):

1. Owner and manager see every credential in the team.
2. Everybody else sees only credentials they created, plus credentials shared
   with them **one user at a time** via `CredentialShare`.

The agency is organised into groups of people (a web team, an SEO team). The web
team manages the passwords for every client website; the SEO team needs a short,
explicit list. Expressing that with per-user shares means re-sharing every new
credential with every web team member by hand, and one forgotten share is a
support ticket. There is no object in the system that means "the web team".

## Decisions taken

| Question | Decision |
| --- | --- |
| What is a "team" here? | A group of **people** inside the tenant `Team` (not a group of clients, not the tenant itself). |
| Who manages groups? | **Owner only** — where a team may have several owners. See the amendments below. |
| Who grants a group access to a credential? | **Owner only.** Managers keep their existing read-everything access but cannot widen access for anyone. |
| Groups per person | **Exactly one** (nullable at the DB level; see below). |
| Does a group grant reveal plaintext? | Owner chooses per grant. **Default is no-reveal.** |
| Grant scope | **Both** a standing blanket rule (all credentials, or all of certain credential types) **and** per-credential grants. |

### Amendment (2026-09-18, superseded the same day): managers administer groups

Group management and credential grants were briefly widened to manager-or-owner,
to answer the owner lockout described below. **This was reverted** — see the
next amendment. It is recorded rather than deleted because the problem it was
solving is real, and the replacement only makes sense against it.

### Amendment (2026-09-18): the gate stays owner-only, and a team may have several owners

The lockout below is a real cost, but widening the gate charged it to the wrong
account. A manager already reads every credential in the team
(`Credential.objects.visible_to`), so admitting them granted nothing new about
what *they* can see — what it handed over was the ability to give that same
reach to **other** people, which is precisely the power this design set out to
keep scarce. Every manager holding it by default is a much larger change than
"the owner is on holiday" warrants.

So the answer to lockout is **a second owner**, not a lower gate:

- The owner role is assignable. An owner can promote any member to owner
  (Team settings → member → Change role → Owner), and can demote or remove a
  co-owner again. It is one deliberate, audit-logged act naming one person,
  rather than a standing grant to a whole tier.
- `Team.owner` is the **primary owner** — the account holder. That one
  membership cannot be demoted or removed: `Team.save` re-creates it and the FK
  is `PROTECT`ed, so "demoting" it would either silently revert or strand the
  team. `TeamMembershipSerializer.is_primary_owner` is how the UI knows which
  row that is; `role == "owner"` no longer tells it, because owners are plural.
- Nobody may change or remove **their own** membership. With the primary owner
  undemotable a team can never run out of owners, but a co-owner who drops their
  own role cannot undo it, and a role change should not also mean "lock me out".

The gate itself lives in two places, one per app, and they must agree:
`apps.accounts.views._require_group_admin` and
`apps.credentials.views.is_group_admin`. Both read the owner role, and both are
the single expression of a check that was once five inline copies.

### Original: accepted trade-off — owner lockout

Strict owner-only means that if the owner is unavailable, nobody can create a
group or grant access. This was chosen deliberately over letting managers grant
access to credentials they created. The escape hatch is out of band: a superuser
via Django admin, or transferring `Team.owner`. Do not soften this in
implementation without a new decision.

*In practice that lockout was the ordinary case rather than the edge case: on an
agency account the owner is one person and managers run the day to day. The
escape hatch is no longer out of band — a team names a second owner in the UI —
but the gate is unchanged.*

## Non-goals

- Groups of clients or websites. A grant is scoped by credential type or by a
  specific credential, never by client.
- Multiple groups per person.
- Groups carrying a role or `feature_access` preset. Role and `feature_access`
  stay exactly as they are; a group governs credential access only.
- Replacing `CredentialShare`. Per-user shares keep working unchanged; group
  grants are an additional path.
- A combined "everyone who can see this credential" endpoint. The share dialog
  reads users and groups from two endpoints instead.

## Architecture

### Models

`SubTeam` goes in `apps/accounts/models.py`, next to `TeamMembership`, because it
groups people:

```python
class SubTeam(BaseModel):
    team = FK("accounts.Team", on_delete=CASCADE, related_name="sub_teams")
    name = CharField(max_length=80)                      # "Web Team", "SEO Team"
    description = CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["name"]
        constraints = [UniqueConstraint(fields=["team", "name"],
                                        name="subteam_unique_name_per_team")]
```

`TeamMembership` gains one column:

```python
sub_team = FK("accounts.SubTeam", null=True, blank=True,
              on_delete=SET_NULL, related_name="memberships")
```

Nullable, because the owner and every existing membership have no group. The
column therefore ships inert: with every row `NULL`, `visible_to` behaves
exactly as it does today.

`SubTeamCredentialGrant` goes in `apps/credentials/models.py`, because it is
credential policy:

```python
class SubTeamCredentialGrant(BaseModel):
    class Scope(models.TextChoices):
        ALL = "all", "All credentials"
        CREDENTIAL_TYPE = "type", "All credentials of a type"
        CREDENTIAL = "credential", "A single credential"

    sub_team = FK("accounts.SubTeam", on_delete=CASCADE,
                  related_name="credential_grants")
    scope = CharField(max_length=12, choices=Scope.choices)
    credential_type = CharField(max_length=30, blank=True, default="")
    credential = FK(Credential, on_delete=CASCADE, null=True, blank=True,
                    related_name="sub_team_grants")
    # Default False, deliberately the opposite of CredentialShare.
    can_view_password = BooleanField(default=False)
    granted_by = FK("accounts.User", on_delete=SET_NULL, null=True, blank=True,
                    related_name="credential_grants_granted")
```

Constraints:

- `UniqueConstraint(sub_team, condition=Q(scope="all"))` gives one blanket rule per group.
- `UniqueConstraint(sub_team, credential_type, condition=Q(scope="type"))`
- `UniqueConstraint(sub_team, credential, condition=Q(scope="credential"))`

One table for both grant kinds, so "who can see this" has a single place to read.

### Validation the database cannot express

Enforced in `clean()` **and** in the serializer (both, because DRF does not call
`clean()`):

- Exactly the field matching `scope` is populated; the other two are blank/null.
- `credential.team_id == sub_team.team_id` when `scope="credential"`.
- `TeamMembership.sub_team.team_id == TeamMembership.team_id` on assignment.

A cross-team assignment is a privilege-escalation bug, not a data-tidiness
issue, so it is rejected at the API boundary with a 400, never coerced.

### Failure direction

Every deletion path removes access and never adds it:

- Deleting a `SubTeam` sets its members' `sub_team` to `NULL` (they fall back to
  own-plus-individual-shares) and cascades its grants away.
- Deleting a `Credential` cascades its per-credential grants.
- A missing or malformed grant row resolves to no access.

### Visibility resolution

`CredentialQuerySet.visible_to(user)` gains a fourth branch. The current three
branches (privileged team membership, creator, per-user share) are untouched.

Resolution order:

1. Read the caller's non-null `sub_team_id`s from `TeamMembership`.
2. Read that group's `SubTeamCredentialGrant` rows.
3. Build one `Q` per scope: `Q(team_id=...)` for `all`,
   `Q(team_id=..., credential_type=...)` for `type`, `Q(pk__in=[...])` for
   `credential`. OR them into the existing filter.

Two small indexed lookups feed the `Q` rather than one nested subquery. This
function is the single gate in front of the entire vault; readability there is
worth two queries. Add an index on `SubTeamCredentialGrant(sub_team, scope)`.

Nothing is materialized into per-user rows. Consequences, all intended:

- A credential created after the grant is covered immediately, with no backfill.
- Moving a member out of a group revokes on their next request.
- There is no generated-versus-hand-made ambiguity in `CredentialShare`.

### Reveal: fixing the fail-open default

`CredentialService.can_view_password` in `apps/credentials/services.py`
currently ends:

```python
return share.can_view_password if share else True
```

With group grants added to `visible_to`, a group member with no share row would
fall through that `else True` and receive full plaintext, silently voiding the
no-reveal default. Rewrite it to be explicit and closed by default:

1. Creator, so `True`.
2. Owner or manager, so `True`.
3. A `CredentialShare` exists, so its `can_view_password`.
4. A matching `SubTeamCredentialGrant` exists, so its `can_view_password`.
5. Otherwise `False`.

**Reveal rights are a union**: if either a share or a grant permits reveal, it is
permitted. Any other precedence rule would be surprising, since a person holding
both got there by both routes. The same union applies when more than one grant
matches (a blanket `all` grant overlapping a `type` grant, say): reveal is
allowed if *any* matching grant allows it. There is no most-specific-wins rule,
so step 3 and step 4 both mean "any permitting row", not "the first row found".

`can_view_password=False` is therefore **not a deny**, it is a grant that does
not include reveal. The system has no deny concept, and inventing one here would
mean a no-reveal individual share silently downgrading somebody's web team
reveal access. Anyone reviewing an access list needs to read it as additive.

Flipping step 5 from `True` to `False` is a no-op for existing data: the only
callers who can currently reach reveal without a share row are creator, owner and
manager, all of whom return `True` at step 1 or 2. A test pins this.

`_assert_can_reveal` keeps blocking the viewer role outright. A viewer inside a
fully granted group still cannot reveal anything. Group grants do not override
role.

### Reveal: fixing the client-controlled `for_autofill` bypass

`CredentialRevealView` reads `for_autofill` from the query string or body, and
`CredentialService.reveal` skips the password check entirely when it is set. Any
holder of a `can_view_password=False` share can therefore call
`/reveal/?for_autofill=1` and read the password. The flag is a UI courtesy today,
not a control.

Changes:

- `CredentialRevealView` (dashboard) stops reading `for_autofill` and always
  honours `can_view_password`.
- Autofill moves to `POST /api/extension/credentials/<pk>/reveal/`
  (`ExtensionCredentialRevealView`), which passes `for_autofill=True` itself.
- New `CredentialAccessLog.Action.AUTOFILL`, recorded separately from a human
  `VIEWED`.
- `extension/background.js` switches to the new route.

**What this does and does not buy.** The extension authenticates with the same
JWT as the dashboard, so a determined user can call the extension route from
devtools. There is no way to hand software a password and simultaneously withhold
it from the person running that software, so "use only" cannot mean "cannot
obtain". It means: never displayed in the dashboard, no single-query-param
toggle, and every autofill pull logged as an autofill against a named user. That
is control by accountability. UI copy must say that, and must not imply the
password is unreachable.

### API surface

Owner-only on every write, checked with
`_my_level(user, team) >= ROLE_LEVELS["owner"]` via `_require_group_admin`
(role-based, not `team.owner`, so every co-owner passes it; consistent with the
rest of `apps/accounts/views.py`, and the primary owner's owner-level membership
is auto-created by `Team.save`). `apps/credentials` applies the same rule
through `is_group_admin`.

```
GET    /api/v1/auth/teams/<team_pk>/sub-teams/            list   (any team member)
POST   /api/v1/auth/teams/<team_pk>/sub-teams/            create (owner)
PATCH  /api/v1/auth/teams/<team_pk>/sub-teams/<pk>/       rename (owner)
DELETE /api/v1/auth/teams/<team_pk>/sub-teams/<pk>/       delete (owner)

GET    /api/v1/sub-teams/<sub_team_pk>/credential-grants/       list   (owner)
POST   /api/v1/sub-teams/<sub_team_pk>/credential-grants/       create (owner)
DELETE /api/v1/sub-teams/<sub_team_pk>/credential-grants/<pk>/  revoke (owner)

GET    /api/v1/credentials/<pk>/group-grants/             grants on one credential (owner)

POST   /api/extension/credentials/<pk>/reveal/            autofill reveal
```

The sub-team list is readable by any team member so the frontend can render a
group badge on a member row. Grants are owner-only to read as well as write.

Two existing endpoints gain one optional `sub_team` field, rejected with 403
unless the caller is the owner:

- `POST /api/v1/auth/teams/<team_pk>/users/` (`TeamCreateUserView`), which is
  the "select the group when the user is added" requirement.
- `PATCH /api/v1/auth/teams/<team_pk>/members/<pk>/` (`TeamMemberDetailView`),
  for moving an existing member between groups.

`GET /api/v1/credentials/<pk>/group-grants/` (owner-only) lists the grants that
reach one specific credential, so the share dialog can show group access next to
user access.

Note this replaces an earlier idea of adding a `groups` array to
`GET /api/v1/credentials/<pk>/shares/`. That endpoint returns a **bare JSON
array** today, so turning it into an object would break the deployed frontend
the moment the backend shipped, and the two halves deploy separately (CLAUDE.md).
The shares endpoint keeps its exact current response shape. Per-credential
grants are *created* through the sub-team collection with `scope="credential"`,
so this is a read-only addition.

`TeamMembershipSerializer` gains read-only `sub_team` (id) and `sub_team_name`.

### Audit

Every sub-team create, rename and delete, every membership group change, and
every grant create and revoke writes an `ActivityLog` row through the existing
`AuditService`, matching what `CredentialShareListCreateView` already does. Grant
entries record `sub_team_id`, `scope`, the target, and `can_view_password`.

### Frontend

`frontend/src/app/(dashboard)/team/page.tsx` additionally fetches
`/auth/teams/<id>/sub-teams/` and passes it to
`frontend/src/components/team-management-client.tsx`, which gains:

- An owner-only **Groups** panel: list, create, rename, delete. The delete
  confirmation names how many members will be left with no group.
- A **Group** select in the add-member form.
- A group badge on each member row, editable by the owner.

Credentials page (`frontend/src/app/(dashboard)/credentials/page.tsx` and its
components):

- A **Groups** tab in the share dialog for per-credential grants, with the
  reveal checkbox defaulting to off.
- An owner-only **Group access** panel for blanket rules: pick a group, choose
  all credentials or specific credential types, set reveal on or off.

`frontend/src/lib/api.ts` gains `SubTeam` and grant types, and `TeamMember`
gains an optional `sub_team`. All new fields are read defensively: per CLAUDE.md
the frontend deploys separately from the backend, so a frontend that ships first
must still render against a backend without these fields.

Naming: `SubTeam` in code, "Groups" in the dashboard, so that "Team" keeps
meaning the agency everywhere in the UI. The group names themselves are the
customer's, so the panel reads "Web Team" and "SEO Team" under a Groups heading.

### Migrations

- `accounts/00XX_subteam` creates `SubTeam` and adds `TeamMembership.sub_team`.
- `credentials/00XX_subteamcredentialgrant` creates the grant table and its
  indexes.

No data migration. Existing memberships get `sub_team=NULL` and existing
`CredentialShare` rows are untouched, so the feature is inert until an owner
creates a group. Run `pytest --create-db` after these land, per CLAUDE.md.

## Testing

TDD throughout. New files `tests/accounts/test_sub_teams.py` and
`tests/credentials/test_group_access.py`. The negative cases carry the value.

**Groups (accounts)**

- Owner creates, renames, deletes a group.
- Manager gets 403 on create, rename, delete, and on setting `sub_team` via
  member PATCH or create-user.
- Duplicate group name in one team is rejected; the same name in another team is
  allowed.
- Assigning a `sub_team` belonging to a different `Team` is rejected with 400.
- Deleting a group sets its members' `sub_team` to `NULL` and removes its grants.

**Group credential access (credentials)**

- A blanket `all` grant makes every team credential visible, including one
  created *after* the grant.
- A `type` grant matches only that `credential_type`.
- A per-credential grant matches only that credential.
- Removing the member from the group revokes access on the next query.
- Deleting the group revokes access.
- Manager gets 403 creating a grant.

**Security regressions (the reason both fixes are in this scope)**

- A grantee with `can_view_password=False` gets `password_hidden=True` and an
  empty password string from the dashboard reveal.
- The same grantee calling the dashboard reveal with `?for_autofill=1` and with
  `{"for_autofill": true}` in the body gets no plaintext.
- A viewer inside a blanket-granted group still cannot reveal.
- Owner, manager and creator reveal exactly as before, which pins the step 5
  `True` to `False` flip as a no-op.
- The extension autofill route returns plaintext for a no-reveal grantee and
  writes a `CredentialAccessLog` row with action `AUTOFILL`.

**Extension**

- `ExtensionCredentialLookupView` honours group grants in both the
  domain-filtered and `all=1` modes.

## Build order

The security fixes land in the **first** commit, not the last, so the group path
never exists in a state where it can leak.

1. Models, migrations, `visible_to` fourth branch, `can_view_password` rewrite,
   `for_autofill` route split, `AUTOFILL` log action, and all backend tests. No
   UI, no API yet.
2. Accounts API: sub-team CRUD, `sub_team` on create-user and member PATCH,
   serializer fields, audit entries.
3. Grants API: grant CRUD, the per-credential grant read endpoint, audit
   entries.
4. Frontend: Groups panel on the team page, Group select in the add-member form,
   group badge on member rows.
5. Frontend: Groups tab in the credential share dialog, Group access panel for
   blanket rules, `extension/background.js` route switch.
