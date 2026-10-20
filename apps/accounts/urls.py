from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.totp_views import (
    AuthRateThrottle,
    FirstPasswordView,
    LoginView,
    PasswordTokenObtainPairView,
    TotpConfirmView,
    TotpDisableView,
    TotpRegenerateBackupView,
    TotpSetupView,
    TotpStatusView,
    TotpVerifyView,
)
from apps.accounts.signup_views import SignupView, TwoFactorReminderDismissView, VerifyEmailView
from apps.accounts.views import (
    ClickUpChannelView,
    ClickUpMembersView,
    ClickUpTestView,
    InvitationAcceptView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    SubTeamDetailView,
    SubTeamListCreateView,
    TeamCreateUserView,
    TeamDetailView,
    TeamInvitationDeleteView,
    TeamInvitationListView,
    TeamInviteView,
    TeamListCreateView,
    TeamMemberDetailView,
    TeamMemberListView,
    TeamSettingsView,
    TeamSwitchView,
)

# Token refresh is fired automatically (every few minutes, server-side) so it
# must use the generous "auth" scope, not the strict daily anon cap.
class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_classes = [AuthRateThrottle]


urlpatterns = [
    # Auth
    # Self-signup creates nothing until the email link is clicked; see
    # apps/accounts/signup_views.py.
    path("signup/", SignupView.as_view(), name="auth-signup"),
    path("verify-email/", VerifyEmailView.as_view(), name="auth-verify-email"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("first-password/", FirstPasswordView.as_view(), name="auth-first-password"),
    # Password-only tokens: refused outside the dev/test 2FA bypass (see view).
    path("token/", PasswordTokenObtainPairView.as_view(), name="auth-token-obtain"),
    path("token/refresh/", ThrottledTokenRefreshView.as_view(), name="auth-token-refresh"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("me/2fa-reminder/dismiss/", TwoFactorReminderDismissView.as_view(), name="auth-2fa-reminder-dismiss"),
    # 2FA
    path("2fa/setup/", TotpSetupView.as_view(), name="2fa-setup"),
    path("2fa/confirm/", TotpConfirmView.as_view(), name="2fa-confirm"),
    path("2fa/verify/", TotpVerifyView.as_view(), name="2fa-verify"),
    path("2fa/disable/", TotpDisableView.as_view(), name="2fa-disable"),
    path("2fa/regenerate-backup/", TotpRegenerateBackupView.as_view(), name="2fa-regenerate-backup"),
    path("2fa/status/", TotpStatusView.as_view(), name="2fa-status"),
    # Teams
    path("teams/", TeamListCreateView.as_view(), name="team-list-create"),
    path("teams/<uuid:pk>/", TeamDetailView.as_view(), name="team-detail"),
    path("teams/<uuid:team_pk>/members/", TeamMemberListView.as_view(), name="team-members"),
    path("teams/<uuid:team_pk>/members/<uuid:pk>/", TeamMemberDetailView.as_view(), name="team-member-detail"),
    path("teams/<uuid:pk>/switch/", TeamSwitchView.as_view(), name="team-switch"),
    # Credential-access groups ("Web Team", "SEO Team"). List is open to any
    # team member so the UI can badge a member; writes are owner-only.
    path("teams/<uuid:team_pk>/sub-teams/", SubTeamListCreateView.as_view(), name="sub-team-list-create"),
    path("teams/<uuid:team_pk>/sub-teams/<uuid:pk>/", SubTeamDetailView.as_view(), name="sub-team-detail"),
    path("teams/<uuid:team_pk>/invite/", TeamInviteView.as_view(), name="team-invite"),
    path("teams/<uuid:team_pk>/users/", TeamCreateUserView.as_view(), name="team-create-user"),
    path("teams/<uuid:team_pk>/invitations/", TeamInvitationListView.as_view(), name="team-invitations"),
    path("teams/<uuid:team_pk>/invitations/<uuid:pk>/", TeamInvitationDeleteView.as_view(), name="team-invitation-delete"),
    path("teams/<uuid:pk>/settings/", TeamSettingsView.as_view(), name="team-settings"),
    path("teams/<uuid:pk>/settings/clickup-test/", ClickUpTestView.as_view(), name="clickup-test"),
    path("teams/<uuid:pk>/settings/clickup-channel/", ClickUpChannelView.as_view(), name="clickup-channel"),
    path("teams/<uuid:pk>/settings/clickup-members/", ClickUpMembersView.as_view(), name="clickup-members"),
    # Invitations
    path("invitations/<str:token>/", InvitationAcceptView.as_view(), name="invitation-view"),
    path("invitations/<str:token>/accept/", InvitationAcceptView.as_view(), name="invitation-accept"),
    # Password reset
    path("password-reset/", PasswordResetRequestView.as_view(), name="password-reset-request"),
    path("password-reset/confirm/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
]
