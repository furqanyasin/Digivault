"""PHP code snippet that powers one-click wp-admin login.

Pasted by the user into the SAME WPCode / Code Snippets tool they already use
for the Digivault tracking script — no separate WordPress plugin to install.
The per-site shared secret is baked in; regenerating it rotates the secret and
invalidates every previously issued login link.

The snippet validates the HMAC-signed, single-use, short-lived token minted by
`WebsiteViewSet.wp_login` and logs the role-mapped user into wp-admin.
"""

_TEMPLATE = r"""<?php
/**
 * Digivault Connect — one-click wp-admin login (no plugin required).
 *
 * Paste this into WPCode or Code Snippets as a PHP snippet, set it to run
 * everywhere / site-wide, and activate it — the same tool you used for the
 * Digivault tracking script. Regenerate from Digivault to rotate the secret.
 */
if ( ! defined( 'ABSPATH' ) ) { return; }

add_action( 'rest_api_init', function () {
	register_rest_route( 'digivault/v1', '/sso', array(
		'methods'             => 'GET',
		'permission_callback' => '__return_true',
		'callback'            => 'dvc_handle_sso',
	) );
} );

if ( ! function_exists( 'dvc_handle_sso' ) ) {
	function dvc_handle_sso( $request ) {
		// Rotating the secret in Digivault replaces the value below.
		$secret        = '__DVC_SECRET__';
		$allowed_roles = array( 'administrator', 'editor' );

		$payload_b64 = (string) $request->get_param( 'p' );
		$signature   = strtolower( (string) $request->get_param( 's' ) );
		if ( '' === $secret || '' === $payload_b64 || '' === $signature ) {
			return new WP_Error( 'dvc_invalid', 'Invalid login token.', array( 'status' => 403 ) );
		}

		// Constant-time signature check.
		$expected = hash_hmac( 'sha256', $payload_b64, $secret );
		if ( ! hash_equals( $expected, $signature ) ) {
			return new WP_Error( 'dvc_invalid', 'Invalid login token.', array( 'status' => 403 ) );
		}

		$b64  = strtr( $payload_b64, '-_', '+/' );
		$b64 .= str_repeat( '=', ( 4 - strlen( $b64 ) % 4 ) % 4 );
		$payload = json_decode( base64_decode( $b64, true ), true );
		if ( ! is_array( $payload ) ) {
			return new WP_Error( 'dvc_invalid', 'Invalid login token.', array( 'status' => 403 ) );
		}

		$email = sanitize_email( isset( $payload['email'] ) ? $payload['email'] : '' );
		$name  = sanitize_text_field( isset( $payload['name'] ) ? $payload['name'] : '' );
		$role  = sanitize_key( isset( $payload['role'] ) ? $payload['role'] : '' );
		$exp   = isset( $payload['exp'] ) ? (int) $payload['exp'] : 0;
		$jti   = sanitize_key( isset( $payload['jti'] ) ? $payload['jti'] : '' );
		if ( ! $email || ! $jti || ! in_array( $role, $allowed_roles, true ) ) {
			return new WP_Error( 'dvc_invalid', 'Invalid login token.', array( 'status' => 403 ) );
		}
		if ( $exp < time() ) {
			return new WP_Error( 'dvc_expired', 'This login link has expired.', array( 'status' => 403 ) );
		}

		// Single use: burn the token id before logging in.
		$jti_key = 'dvc_jti_' . $jti;
		if ( false !== get_transient( $jti_key ) ) {
			return new WP_Error( 'dvc_invalid', 'Invalid login token.', array( 'status' => 403 ) );
		}
		set_transient( $jti_key, 1, 15 * MINUTE_IN_SECONDS );

		$user = get_user_by( 'email', $email );
		if ( ! $user ) {
			$login = sanitize_user( strstr( $email, '@', true ) . '_dv', true );
			$uid   = wp_insert_user( array(
				'user_login'   => $login,
				'user_email'   => $email,
				'user_pass'    => wp_generate_password( 32, true, true ),
				'display_name' => $name ? $name : $login,
				'role'         => $role,
			) );
			if ( is_wp_error( $uid ) ) {
				return new WP_Error( 'dvc_user', 'Could not provision a WordPress user.', array( 'status' => 500 ) );
			}
			$user = get_user_by( 'id', $uid );
		} elseif ( empty( $user->roles ) ) {
			$user->set_role( $role );
		}

		wp_set_current_user( $user->ID );
		wp_set_auth_cookie( $user->ID, false );
		do_action( 'wp_login', $user->user_login, $user );
		wp_safe_redirect( admin_url() );
		exit;
	}
}
"""


def build_wp_sso_snippet(secret: str) -> str:
    """Return the ready-to-paste PHP snippet with the secret baked in."""
    if not secret:
        return ""
    return _TEMPLATE.replace("__DVC_SECRET__", secret)
