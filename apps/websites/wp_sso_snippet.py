"""PHP code snippet that powers one-click wp-admin login and form-recipient reads.

Pasted by the user into the SAME WPCode / Code Snippets tool they already use
for the Digivault tracking script — no separate WordPress plugin to install.
The per-site shared secret is baked in; regenerating it rotates the secret and
invalidates every previously issued login link.

The snippet validates the HMAC-signed, single-use, short-lived token minted by
`WebsiteViewSet.wp_login` and logs the role-mapped user into wp-admin.

It also answers `digivault/v1/forms` — likewise signature-gated — with where each
form plugin is configured to send submissions. That address lives in the database
(Elementor's `_elementor_data`, CF7's `_mail`, and so on) and never reaches the
page, so it is invisible to the tracking snippet; this route is the only way the
Forms tab can show it.
"""

_TEMPLATE = r"""<?php
/**
 * Digivault Connect — one-click wp-admin login + form recipients (no plugin required).
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
	register_rest_route( 'digivault/v1', '/forms', array(
		'methods'             => 'GET',
		'permission_callback' => '__return_true',
		'callback'            => 'dvc_handle_forms',
	) );
} );

/**
 * Verify a Digivault-signed request. Returns the payload array, or false.
 *
 * The signature is mandatory on every route. /forms answers with staff mailboxes,
 * so an unsigned route would publish this site's admin addresses to anyone who
 * guessed the path.
 */
if ( ! function_exists( 'dvc_verify_token' ) ) {
	function dvc_verify_token( $request, $secret ) {
		$payload_b64 = (string) $request->get_param( 'p' );
		$signature   = strtolower( (string) $request->get_param( 's' ) );
		if ( '' === $secret || '' === $payload_b64 || '' === $signature ) {
			return false;
		}
		$expected = hash_hmac( 'sha256', $payload_b64, $secret );
		if ( ! hash_equals( $expected, $signature ) ) {
			return false;
		}
		$b64  = strtr( $payload_b64, '-_', '+/' );
		$b64 .= str_repeat( '=', ( 4 - strlen( $b64 ) % 4 ) % 4 );
		$payload = json_decode( base64_decode( $b64, true ), true );
		if ( ! is_array( $payload ) ) {
			return false;
		}
		$exp = isset( $payload['exp'] ) ? (int) $payload['exp'] : 0;
		if ( $exp < time() ) {
			return false;
		}
		return $payload;
	}
}

/** An address, or '' — resolving the placeholders each plugin allows here. */
if ( ! function_exists( 'dvc_clean_email' ) ) {
	function dvc_clean_email( $value ) {
		$value = trim( (string) $value );
		if ( '' === $value ) {
			return '';
		}
		// [_site_admin_email] (CF7), {admin_email} (WPForms, Gravity).
		if ( preg_match( '/^[\[{]_?(site_)?admin_email[\]}]$/i', $value ) ) {
			return (string) get_option( 'admin_email' );
		}
		// A "Name <addr>" value: keep the address.
		if ( preg_match( '/<([^>]+)>/', $value, $m ) ) {
			$value = $m[1];
		}
		// Anything still carrying a template tag is a per-submission value
		// (usually the visitor's own address) and is not a destination.
		if ( false !== strpos( $value, '[' ) || false !== strpos( $value, '{' ) ) {
			return '';
		}
		$value = sanitize_email( $value );
		return is_email( $value ) ? strtolower( $value ) : '';
	}
}

/** Split a plugin's recipient string ("a@x.com, b@x.com") into addresses. */
if ( ! function_exists( 'dvc_split_emails' ) ) {
	function dvc_split_emails( $value ) {
		$out = array();
		foreach ( preg_split( '/[,;]+/', (string) $value ) as $part ) {
			$email = dvc_clean_email( $part );
			if ( '' !== $email && ! in_array( $email, $out, true ) ) {
				$out[] = $email;
			}
		}
		return $out;
	}
}

/**
 * The first non-empty value among several candidate setting keys.
 *
 * Plugin setting names are not documented API and differ between versions —
 * Elementor's Cc field has been seen as both `email_cc` and `email_to_cc`.
 * Reading a candidate list costs nothing and degrades to "no Cc found" rather
 * than to a wrong answer.
 */
if ( ! function_exists( 'dvc_first_setting' ) ) {
	function dvc_first_setting( $settings, $keys ) {
		foreach ( (array) $keys as $key ) {
			if ( isset( $settings[ $key ] ) && '' !== trim( (string) $settings[ $key ] ) ) {
				return $settings[ $key ];
			}
		}
		return '';
	}
}

/** Cc/Bcc out of an RFC-822 header blob, as Contact Form 7 stores them. */
if ( ! function_exists( 'dvc_headers_copies' ) ) {
	function dvc_headers_copies( $headers ) {
		$out = array( 'cc' => array(), 'bcc' => array() );
		foreach ( preg_split( '/\r\n|\r|\n/', (string) $headers ) as $line ) {
			if ( preg_match( '/^\s*(bcc|cc)\s*:\s*(.+)$/i', $line, $m ) ) {
				$kind = strtolower( $m[1] );
				$out[ $kind ] = array_merge( $out[ $kind ], dvc_split_emails( $m[2] ) );
			}
		}
		return $out;
	}
}

/**
 * Where each form on this site is configured to send its submissions.
 *
 * Digivault's tracking snippet can only read a recipient that appears in the
 * page's HTML. Every WordPress form plugin keeps it in the database instead, so
 * this route is the only way the Forms tab can show it. Each reader is guarded:
 * a site without that plugin contributes nothing rather than fataling.
 */
if ( ! function_exists( 'dvc_handle_forms' ) ) {
	function dvc_handle_forms( $request ) {
		// Rotating the secret in Digivault replaces the value below.
		$secret = '__DVC_SECRET__';

		if ( ! dvc_verify_token( $request, $secret ) ) {
			return new WP_Error( 'dvc_invalid', 'Invalid request.', array( 'status' => 403 ) );
		}

		$forms = array_merge(
			dvc_forms_elementor(),
			dvc_forms_cf7(),
			dvc_forms_wpforms(),
			dvc_forms_gravity()
		);

		return rest_ensure_response( array( 'forms' => $forms ) );
	}
}

/**
 * Elementor Pro forms, from the page builder's own JSON.
 *
 * Joined on the form name, because Elementor renders it as the form element's
 * `name` attribute — which is what the snippet already stores. An email action
 * with an empty "To" falls back to the site admin address, exactly as Elementor
 * itself does at send time.
 */
if ( ! function_exists( 'dvc_forms_elementor' ) ) {
	function dvc_forms_elementor() {
		global $wpdb;
		if ( ! defined( 'ELEMENTOR_VERSION' ) ) {
			return array();
		}
		$rows = $wpdb->get_col(
			"SELECT meta_value FROM {$wpdb->postmeta}
			 WHERE meta_key = '_elementor_data'
			   AND meta_value LIKE '%\"widgetType\":\"form\"%'
			 LIMIT 200"
		);
		$out = array();
		foreach ( (array) $rows as $json ) {
			$tree = json_decode( $json, true );
			if ( is_array( $tree ) ) {
				dvc_walk_elementor( $tree, $out );
			}
		}
		return $out;
	}
}

if ( ! function_exists( 'dvc_walk_elementor' ) ) {
	function dvc_walk_elementor( $elements, &$out ) {
		foreach ( (array) $elements as $el ) {
			if ( ! is_array( $el ) ) {
				continue;
			}
			if ( isset( $el['widgetType'] ) && 'form' === $el['widgetType'] ) {
				$s       = isset( $el['settings'] ) && is_array( $el['settings'] ) ? $el['settings'] : array();
				$actions = isset( $s['submit_actions'] ) ? (array) $s['submit_actions'] : array();
				if ( in_array( 'email', $actions, true ) ) {
					$to = isset( $s['email_to'] ) ? dvc_split_emails( $s['email_to'] ) : array();
					if ( empty( $to ) ) {
						$admin = dvc_clean_email( get_option( 'admin_email' ) );
						if ( '' !== $admin ) {
							$to = array( $admin );
						}
					}
					if ( ! empty( $to ) ) {
						$out[] = array(
							'plugin'    => 'elementor',
							'name'      => isset( $s['form_name'] ) ? (string) $s['form_name'] : '',
							'id_prefix' => '',
							'to'        => $to,
							'cc'        => dvc_split_emails( dvc_first_setting( $s, array( 'email_cc', 'email_to_cc' ) ) ),
							'bcc'       => dvc_split_emails( dvc_first_setting( $s, array( 'email_bcc', 'email_to_bcc' ) ) ),
						);
					}
				}
			}
			if ( ! empty( $el['elements'] ) ) {
				dvc_walk_elementor( $el['elements'], $out );
			}
		}
	}
}

/** Contact Form 7 — joined on the `wpcf7-f{ID}-` prefix of its form id. */
if ( ! function_exists( 'dvc_forms_cf7' ) ) {
	function dvc_forms_cf7() {
		if ( ! class_exists( 'WPCF7_ContactForm' ) ) {
			return array();
		}
		$out   = array();
		$posts = get_posts( array(
			'post_type'        => 'wpcf7_contact_form',
			'post_status'      => 'any',
			'numberposts'      => 100,
			'suppress_filters' => true,
		) );
		foreach ( $posts as $post ) {
			$mail = get_post_meta( $post->ID, '_mail', true );
			$to   = is_array( $mail ) && isset( $mail['recipient'] )
				? dvc_split_emails( $mail['recipient'] )
				: array();
			$copies = is_array( $mail ) && isset( $mail['additional_headers'] )
				? dvc_headers_copies( $mail['additional_headers'] )
				: array( 'cc' => array(), 'bcc' => array() );
			if ( ! empty( $to ) ) {
				$out[] = array(
					'plugin'    => 'contact-form-7',
					'name'      => $post->post_title,
					'id_prefix' => 'wpcf7-f' . $post->ID . '-',
					'to'        => $to,
					'cc'        => $copies['cc'],
					'bcc'       => $copies['bcc'],
				);
			}
		}
		return $out;
	}
}

/** WPForms — joined on the `wpforms-form-{ID}` form id. */
if ( ! function_exists( 'dvc_forms_wpforms' ) ) {
	function dvc_forms_wpforms() {
		if ( ! post_type_exists( 'wpforms' ) ) {
			return array();
		}
		$out   = array();
		$posts = get_posts( array(
			'post_type'        => 'wpforms',
			'post_status'      => 'any',
			'numberposts'      => 100,
			'suppress_filters' => true,
		) );
		foreach ( $posts as $post ) {
			$data = json_decode( $post->post_content, true );
			if ( ! is_array( $data ) ) {
				continue;
			}
			$notifications = isset( $data['settings']['notifications'] )
				? (array) $data['settings']['notifications']
				: array();
			$to  = array();
			$cc  = array();
			$bcc = array();
			foreach ( $notifications as $n ) {
				if ( ! is_array( $n ) ) {
					continue;
				}
				if ( isset( $n['email'] ) ) {
					$to = array_merge( $to, dvc_split_emails( $n['email'] ) );
				}
				$cc  = array_merge( $cc, dvc_split_emails( dvc_first_setting( $n, array( 'carboncopy', 'cc' ) ) ) );
				$bcc = array_merge( $bcc, dvc_split_emails( dvc_first_setting( $n, array( 'blindcarboncopy', 'bcc' ) ) ) );
			}
			$to  = array_values( array_unique( $to ) );
			$cc  = array_values( array_unique( $cc ) );
			$bcc = array_values( array_unique( $bcc ) );
			if ( ! empty( $to ) ) {
				$out[] = array(
					'plugin'    => 'wpforms',
					'name'      => $post->post_title,
					'id_prefix' => 'wpforms-form-' . $post->ID,
					'to'        => $to,
					'cc'        => $cc,
					'bcc'       => $bcc,
				);
			}
		}
		return $out;
	}
}

/** Gravity Forms — joined on the `gform_{ID}` form id. */
if ( ! function_exists( 'dvc_forms_gravity' ) ) {
	function dvc_forms_gravity() {
		if ( ! class_exists( 'GFAPI' ) ) {
			return array();
		}
		$out = array();
		foreach ( (array) GFAPI::get_forms() as $form ) {
			$to  = array();
			$cc  = array();
			$bcc = array();
			foreach ( (array) ( isset( $form['notifications'] ) ? $form['notifications'] : array() ) as $n ) {
				if ( ! is_array( $n ) ) {
					continue;
				}
				// A notification routed to a field carries the visitor's address,
				// not a destination the agency configured.
				if ( isset( $n['to'] ) && ( ! isset( $n['toType'] ) || 'email' === $n['toType'] ) ) {
					$to = array_merge( $to, dvc_split_emails( $n['to'] ) );
				}
				if ( isset( $n['cc'] ) ) {
					$cc = array_merge( $cc, dvc_split_emails( $n['cc'] ) );
				}
				if ( isset( $n['bcc'] ) ) {
					$bcc = array_merge( $bcc, dvc_split_emails( $n['bcc'] ) );
				}
			}
			$to  = array_values( array_unique( $to ) );
			$cc  = array_values( array_unique( $cc ) );
			$bcc = array_values( array_unique( $bcc ) );
			if ( ! empty( $to ) ) {
				$out[] = array(
					'plugin'    => 'gravity-forms',
					'name'      => isset( $form['title'] ) ? (string) $form['title'] : '',
					'id_prefix' => 'gform_' . $form['id'],
					'to'        => $to,
					'cc'        => $cc,
					'bcc'       => $bcc,
				);
			}
		}
		return $out;
	}
}

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
