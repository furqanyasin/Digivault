"""PHP code snippet that powers one-click wp-admin login and form-recipient reads.

Pasted by the user into the SAME WPCode / Code Snippets tool they already use
for the Stacks Monitor tracking script — no separate WordPress plugin to install.
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

# The version stamped into the template and reported by every activity flush.
# Single source of truth: the rollout badge compares a site's reported version
# against this, so a second constant elsewhere would drift and make the badge
# confidently wrong.
SNIPPET_VERSION = 2

_TEMPLATE = r"""<?php
/**
 * Stacks Monitor Connect — one-click wp-admin login + form recipients (no plugin required).
 *
 * Paste this into WPCode or Code Snippets as a PHP snippet, set it to run
 * everywhere / site-wide, and activate it — the same tool you used for the
 * Stacks Monitor tracking script. Regenerate from Stacks Monitor to rotate the secret.
 */
if ( ! defined( 'ABSPATH' ) ) { return; }

/**
 * Version arbitration. A client who ADDS this snippet beside an older one --
 * rather than replacing it -- would otherwise get the old snippet's function
 * bodies bound to this one's route registrations, silently and with no error.
 * Every symbol below is version-suffixed so both can coexist, and the highest
 * version present wins. MalCare solves the identical problem the same way.
 */
if ( defined( 'DVC_VERSION' ) && DVC_VERSION >= 2 ) { return; }
if ( ! defined( 'DVC_VERSION' ) ) { define( 'DVC_VERSION', 2 ); }

define( 'DVC2_SECRET',     '__DVC_SECRET__' );
define( 'DVC2_SITE_ID',    '__DVC_SITE_ID__' );
define( 'DVC2_INGEST_URL', '__DVC_INGEST_URL__' );

/** Hard caps. One hot hook in a loop must not fill the client's database. */
define( 'DVC2_MAX_ROWS',    10000 );
define( 'DVC2_MAX_DETAILS', 1024 );
define( 'DVC2_DEAD_DAYS',   7 );

/** The buffer table. Created lazily; its autoincrement id is the sequence. */
if ( ! function_exists( 'dvc2_table' ) ) {
	function dvc2_table() {
		global $wpdb;
		return $wpdb->prefix . 'digivault_events';
	}
}

if ( ! function_exists( 'dvc2_ensure_table' ) ) {
	function dvc2_ensure_table() {
		if ( get_option( 'dvc2_db_version' ) === '2' ) { return; }
		global $wpdb;
		require_once ABSPATH . 'wp-admin/includes/upgrade.php';
		$table   = dvc2_table();
		$collate = $wpdb->get_charset_collate();
		dbDelta( "CREATE TABLE {$table} (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			occurred_at DATETIME NOT NULL,
			event_type VARCHAR(40) NOT NULL,
			actor_login VARCHAR(200) NOT NULL DEFAULT '',
			actor_id BIGINT NULL,
			actor_ip VARCHAR(45) NOT NULL DEFAULT '',
			object_type VARCHAR(30) NOT NULL DEFAULT '',
			object_id VARCHAR(200) NOT NULL DEFAULT '',
			summary VARCHAR(500) NOT NULL DEFAULT '',
			details TEXT NULL,
			sent_at DATETIME NULL,
			PRIMARY KEY (id),
			KEY sent_at (sent_at)
		) {$collate};" );
		update_option( 'dvc2_db_version', '2', false );
	}
}

/**
 * The dead-man switch. A snippet has no uninstall hook, so a client who cancels
 * Stacks Monitor -- or a site we can no longer reach -- would otherwise buffer events
 * into their database forever. MalCare does the same with bvwatchtime.
 */
if ( ! function_exists( 'dvc2_is_active' ) ) {
	function dvc2_is_active() {
		$last = (int) get_option( 'dvc2_last_ack', 0 );
		if ( 0 === $last ) {
			// Never acked: collect during a grace window so the first flush has
			// something to send, then stop if nobody is listening.
			$first = (int) get_option( 'dvc2_installed_at', 0 );
			if ( 0 === $first ) {
				update_option( 'dvc2_installed_at', time(), false );
				return true;
			}
			return ( time() - $first ) < ( DVC2_DEAD_DAYS * DAY_IN_SECONDS );
		}
		return ( time() - $last ) < ( DVC2_DEAD_DAYS * DAY_IN_SECONDS );
	}
}

/**
 * Drop anything not explicitly allowed through. An allowlist, not a blocklist:
 * these hooks carry password and token material, and a blocklist is one new
 * WordPress release away from leaking it.
 */
if ( ! function_exists( 'dvc2_redact' ) ) {
	function dvc2_redact( $details ) {
		$allowed = array(
			'role', 'old_role', 'new_role', 'status', 'old_status', 'new_status',
			'slug', 'version', 'old_version', 'name', 'title', 'post_type',
			'order_id', 'total', 'currency', 'dropped', 'reason',
		);
		$out = array();
		foreach ( (array) $details as $key => $value ) {
			if ( in_array( $key, $allowed, true ) && is_scalar( $value ) ) {
				$out[ $key ] = substr( (string) $value, 0, 200 );
			}
		}
		return $out;
	}
}

if ( ! function_exists( 'dvc2_client_ip' ) ) {
	function dvc2_client_ip() {
		foreach ( array( 'HTTP_CF_CONNECTING_IP', 'HTTP_X_FORWARDED_FOR', 'REMOTE_ADDR' ) as $key ) {
			if ( empty( $_SERVER[ $key ] ) ) { continue; }
			$parts     = explode( ',', (string) $_SERVER[ $key ] );
			$candidate = trim( $parts[0] );
			if ( filter_var( $candidate, FILTER_VALIDATE_IP ) ) { return $candidate; }
		}
		return '';
	}
}

/**
 * Record one event. Never throws: a collector fault must not break the client's
 * site, so every failure here is swallowed deliberately.
 */
if ( ! function_exists( 'dvc2_record' ) ) {
	function dvc2_record( $type, $summary, $details = array(), $object_type = '', $object_id = '' ) {
		try {
			if ( ! dvc2_is_active() ) { return; }
			dvc2_ensure_table();
			global $wpdb;
			$table = dvc2_table();

			$count = (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$table}" );
			if ( $count >= DVC2_MAX_ROWS ) {
				// Drop the oldest tenth and say so, rather than silently losing
				// the newest events or growing without bound.
				$cut = (int) ( DVC2_MAX_ROWS / 10 );
				$wpdb->query( "DELETE FROM {$table} ORDER BY id ASC LIMIT {$cut}" );
				$type    = 'buffer_overflow';
				$summary = 'Event buffer overflowed; oldest events were dropped.';
				$details = array( 'dropped' => $cut );
			}

			$user = function_exists( 'wp_get_current_user' ) ? wp_get_current_user() : null;
			$wpdb->insert( $table, array(
				'occurred_at' => gmdate( 'Y-m-d H:i:s' ),
				'event_type'  => substr( (string) $type, 0, 40 ),
				'actor_login' => ( $user && $user->ID ) ? substr( $user->user_login, 0, 200 ) : '',
				'actor_id'    => ( $user && $user->ID ) ? (int) $user->ID : null,
				'actor_ip'    => dvc2_client_ip(),
				'object_type' => substr( (string) $object_type, 0, 30 ),
				'object_id'   => substr( (string) $object_id, 0, 200 ),
				'summary'     => substr( (string) $summary, 0, 500 ),
				'details'     => substr( wp_json_encode( dvc2_redact( $details ) ), 0, DVC2_MAX_DETAILS ),
			) );
		} catch ( Exception $e ) {
			return;
		} catch ( Error $e ) {
			return;
		}
	}
}

add_action( 'rest_api_init', function () {
	register_rest_route( 'digivault/v1', '/sso', array(
		'methods'             => 'GET',
		'permission_callback' => '__return_true',
		'callback'            => 'dvc2_handle_sso',
	) );
	register_rest_route( 'digivault/v1', '/forms', array(
		'methods'             => 'GET',
		'permission_callback' => '__return_true',
		'callback'            => 'dvc2_handle_forms',
	) );
} );

/**
 * Verify a request signed by Stacks Monitor. Returns the payload array, or false.
 *
 * The signature is mandatory on every route. /forms answers with staff mailboxes,
 * so an unsigned route would publish this site's admin addresses to anyone who
 * guessed the path.
 */
if ( ! function_exists( 'dvc2_verify_token' ) ) {
	function dvc2_verify_token( $request, $secret ) {
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
if ( ! function_exists( 'dvc2_clean_email' ) ) {
	function dvc2_clean_email( $value ) {
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
if ( ! function_exists( 'dvc2_split_emails' ) ) {
	function dvc2_split_emails( $value ) {
		$out = array();
		foreach ( preg_split( '/[,;]+/', (string) $value ) as $part ) {
			$email = dvc2_clean_email( $part );
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
if ( ! function_exists( 'dvc2_first_setting' ) ) {
	function dvc2_first_setting( $settings, $keys ) {
		foreach ( (array) $keys as $key ) {
			// A plugin can store a setting as an array (a multi-recipient field
			// saved as a list, say). is_scalar() skips it like an empty value
			// instead of letting (string) cast it and emit an "Array to string
			// conversion" notice — on a site with WP_DEBUG_DISPLAY on, that
			// notice prints inside this REST response and corrupts the JSON.
			if ( isset( $settings[ $key ] ) && is_scalar( $settings[ $key ] )
				&& '' !== trim( (string) $settings[ $key ] ) ) {
				return $settings[ $key ];
			}
		}
		return '';
	}
}

/** Cc/Bcc out of an RFC-822 header blob, as Contact Form 7 stores them. */
if ( ! function_exists( 'dvc2_headers_copies' ) ) {
	function dvc2_headers_copies( $headers ) {
		$out = array( 'cc' => array(), 'bcc' => array() );
		foreach ( preg_split( '/\r\n|\r|\n/', (string) $headers ) as $line ) {
			if ( preg_match( '/^\s*(bcc|cc)\s*:\s*(.+)$/i', $line, $m ) ) {
				$kind = strtolower( $m[1] );
				$out[ $kind ] = array_merge( $out[ $kind ], dvc2_split_emails( $m[2] ) );
			}
		}
		return $out;
	}
}

/**
 * Where each form on this site is configured to send its submissions.
 *
 * Stacks Monitor's tracking snippet can only read a recipient that appears in the
 * page's HTML. Every WordPress form plugin keeps it in the database instead, so
 * this route is the only way the Forms tab can show it. Each reader is guarded:
 * a site without that plugin contributes nothing rather than fataling.
 */
if ( ! function_exists( 'dvc2_handle_forms' ) ) {
	function dvc2_handle_forms( $request ) {
		// Rotating the secret in Stacks Monitor replaces the value below.
		$secret = DVC2_SECRET;

		if ( ! dvc2_verify_token( $request, $secret ) ) {
			return new WP_Error( 'dvc2_invalid', 'Invalid request.', array( 'status' => 403 ) );
		}

		$forms = array_merge(
			dvc2_forms_elementor(),
			dvc2_forms_cf7(),
			dvc2_forms_wpforms(),
			dvc2_forms_gravity()
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
if ( ! function_exists( 'dvc2_forms_elementor' ) ) {
	function dvc2_forms_elementor() {
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
				dvc2_walk_elementor( $tree, $out );
			}
		}
		return $out;
	}
}

if ( ! function_exists( 'dvc2_walk_elementor' ) ) {
	function dvc2_walk_elementor( $elements, &$out ) {
		foreach ( (array) $elements as $el ) {
			if ( ! is_array( $el ) ) {
				continue;
			}
			if ( isset( $el['widgetType'] ) && 'form' === $el['widgetType'] ) {
				$s       = isset( $el['settings'] ) && is_array( $el['settings'] ) ? $el['settings'] : array();
				$actions = isset( $s['submit_actions'] ) ? (array) $s['submit_actions'] : array();
				if ( in_array( 'email', $actions, true ) ) {
					$to = isset( $s['email_to'] ) ? dvc2_split_emails( $s['email_to'] ) : array();
					if ( empty( $to ) ) {
						$admin = dvc2_clean_email( get_option( 'admin_email' ) );
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
							'cc'        => dvc2_split_emails( dvc2_first_setting( $s, array( 'email_cc', 'email_to_cc' ) ) ),
							'bcc'       => dvc2_split_emails( dvc2_first_setting( $s, array( 'email_bcc', 'email_to_bcc' ) ) ),
						);
					}
				}
			}
			if ( ! empty( $el['elements'] ) ) {
				dvc2_walk_elementor( $el['elements'], $out );
			}
		}
	}
}

/** Contact Form 7 — joined on the `wpcf7-f{ID}-` prefix of its form id. */
if ( ! function_exists( 'dvc2_forms_cf7' ) ) {
	function dvc2_forms_cf7() {
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
				? dvc2_split_emails( $mail['recipient'] )
				: array();
			$copies = is_array( $mail ) && isset( $mail['additional_headers'] )
				? dvc2_headers_copies( $mail['additional_headers'] )
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
if ( ! function_exists( 'dvc2_forms_wpforms' ) ) {
	function dvc2_forms_wpforms() {
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
					$to = array_merge( $to, dvc2_split_emails( $n['email'] ) );
				}
				$cc  = array_merge( $cc, dvc2_split_emails( dvc2_first_setting( $n, array( 'carboncopy', 'cc' ) ) ) );
				$bcc = array_merge( $bcc, dvc2_split_emails( dvc2_first_setting( $n, array( 'blindcarboncopy', 'bcc' ) ) ) );
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
if ( ! function_exists( 'dvc2_forms_gravity' ) ) {
	function dvc2_forms_gravity() {
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
					$to = array_merge( $to, dvc2_split_emails( $n['to'] ) );
				}
				if ( isset( $n['cc'] ) ) {
					$cc = array_merge( $cc, dvc2_split_emails( $n['cc'] ) );
				}
				if ( isset( $n['bcc'] ) ) {
					$bcc = array_merge( $bcc, dvc2_split_emails( $n['bcc'] ) );
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

if ( ! function_exists( 'dvc2_handle_sso' ) ) {
	function dvc2_handle_sso( $request ) {
		// Rotating the secret in Stacks Monitor replaces the value below.
		$secret        = DVC2_SECRET;
		$allowed_roles = array( 'administrator', 'editor' );

		$payload_b64 = (string) $request->get_param( 'p' );
		$signature   = strtolower( (string) $request->get_param( 's' ) );
		if ( '' === $secret || '' === $payload_b64 || '' === $signature ) {
			return new WP_Error( 'dvc2_invalid', 'Invalid login token.', array( 'status' => 403 ) );
		}

		// Constant-time signature check.
		$expected = hash_hmac( 'sha256', $payload_b64, $secret );
		if ( ! hash_equals( $expected, $signature ) ) {
			return new WP_Error( 'dvc2_invalid', 'Invalid login token.', array( 'status' => 403 ) );
		}

		$b64  = strtr( $payload_b64, '-_', '+/' );
		$b64 .= str_repeat( '=', ( 4 - strlen( $b64 ) % 4 ) % 4 );
		$payload = json_decode( base64_decode( $b64, true ), true );
		if ( ! is_array( $payload ) ) {
			return new WP_Error( 'dvc2_invalid', 'Invalid login token.', array( 'status' => 403 ) );
		}

		$email = sanitize_email( isset( $payload['email'] ) ? $payload['email'] : '' );
		$name  = sanitize_text_field( isset( $payload['name'] ) ? $payload['name'] : '' );
		$role  = sanitize_key( isset( $payload['role'] ) ? $payload['role'] : '' );
		$exp   = isset( $payload['exp'] ) ? (int) $payload['exp'] : 0;
		$jti   = sanitize_key( isset( $payload['jti'] ) ? $payload['jti'] : '' );
		if ( ! $email || ! $jti || ! in_array( $role, $allowed_roles, true ) ) {
			return new WP_Error( 'dvc2_invalid', 'Invalid login token.', array( 'status' => 403 ) );
		}
		if ( $exp < time() ) {
			return new WP_Error( 'dvc2_expired', 'This login link has expired.', array( 'status' => 403 ) );
		}

		// Single use: burn the token id before logging in.
		$jti_key = 'dvc2_jti_' . $jti;
		if ( false !== get_transient( $jti_key ) ) {
			return new WP_Error( 'dvc2_invalid', 'Invalid login token.', array( 'status' => 403 ) );
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
				return new WP_Error( 'dvc2_user', 'Could not provision a WordPress user.', array( 'status' => 500 ) );
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

/**
 * Send buffered events. Batched rather than one POST per hook: a request to
 * Stacks Monitor inside `user_register` would put our latency on the client's admin.
 */
if ( ! function_exists( 'dvc2_flush' ) ) {
	function dvc2_flush( $resend_from = null, $heartbeat = null ) {
		try {
			if ( '' === DVC2_INGEST_URL || '' === DVC2_SITE_ID ) { return; }
			global $wpdb;
			$table = dvc2_table();
			if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $table ) ) !== $table ) { return; }

			$where = ( null === $resend_from ) ? '' : $wpdb->prepare( 'WHERE id >= %d', (int) $resend_from );
			$rows  = $wpdb->get_results( "SELECT * FROM {$table} {$where} ORDER BY id ASC LIMIT 200", ARRAY_A );
			$manifest = get_option( 'dvc2_pending_manifest', null );
			if ( empty( $rows ) && empty( $manifest ) && null === $heartbeat ) { return; }

			$events = array();
			foreach ( (array) $rows as $row ) {
				$events[] = array(
					'seq'         => (int) $row['id'],
					'type'        => $row['event_type'],
					'occurred_at' => gmdate( 'c', strtotime( $row['occurred_at'] . ' UTC' ) ),
					'summary'     => $row['summary'],
					'actor_login' => $row['actor_login'],
					'actor_id'    => ( null === $row['actor_id'] ) ? null : (int) $row['actor_id'],
					'actor_ip'    => ( '' === $row['actor_ip'] ) ? null : $row['actor_ip'],
					'object_type' => $row['object_type'],
					'object_id'   => $row['object_id'],
					'details'     => json_decode( (string) $row['details'], true ),
				);
			}

			$payload = array( 'snippet_version' => DVC_VERSION, 'events' => $events );
			if ( ! empty( $manifest ) ) { $payload['manifest'] = $manifest; }
			if ( null !== $heartbeat ) { $payload['heartbeat'] = $heartbeat; }

			$body = wp_json_encode( $payload );
			$ts   = (string) time();
			$sig  = hash_hmac( 'sha256', $ts . '.' . $body, DVC2_SECRET );

			$response = wp_remote_post( DVC2_INGEST_URL, array(
				'timeout'  => 5,
				'blocking' => true,
				'headers'  => array(
					'Content-Type'          => 'application/json',
					'X-Digivault-Site'      => DVC2_SITE_ID,
					'X-Digivault-Timestamp' => $ts,
					'X-Digivault-Signature' => $sig,
				),
				'body'     => $body,
			) );

			if ( is_wp_error( $response ) || 202 !== (int) wp_remote_retrieve_response_code( $response ) ) {
				return;
			}

			// Acked. Delete rather than mark sent: unacked rows must survive to
			// be re-sent, and the autoincrement keeps advancing past deletions
			// so the sequence stays monotonic.
			if ( ! empty( $rows ) ) {
				$highest = (int) $rows[ count( $rows ) - 1 ]['id'];
				$wpdb->query( $wpdb->prepare( "DELETE FROM {$table} WHERE id <= %d", $highest ) );
			}
			delete_option( 'dvc2_pending_manifest' );
			update_option( 'dvc2_last_ack', time(), false );

			$decoded = json_decode( (string) wp_remote_retrieve_body( $response ), true );
			$data    = isset( $decoded['data'] ) ? $decoded['data'] : $decoded;
			if ( is_array( $data ) && isset( $data['resend_from'] ) && null !== $data['resend_from'] ) {
				dvc2_flush( (int) $data['resend_from'] );
			}
		} catch ( Exception $e ) {
			return;
		} catch ( Error $e ) {
			return;
		}
	}
}

add_action( 'shutdown', 'dvc2_flush', 999 );

/**
 * Heartbeat: fetch our own homepage from this server and report the answer.
 * Host firewalls (SiteGround's anti-bot above all) challenge Stacks Monitor's
 * monitoring IP, so from outside a working site reads "blocked". This request
 * leaves from the site's own server and the report goes OUT to Stacks Monitor, so
 * no firewall in front of the site is in the way of either. Cron only, never
 * on `shutdown`: the loopback would otherwise sit inside a visitor's request.
 */
if ( ! function_exists( 'dvc2_heartbeat' ) ) {
	function dvc2_heartbeat() {
		$status = null;
		$ms     = null;
		try {
			$start    = microtime( true );
			$response = wp_remote_get( home_url( '/' ), array(
				'timeout'     => 10,
				'redirection' => 3,
				'sslverify'   => apply_filters( 'https_local_ssl_verify', false ),
				'user-agent'  => 'Digivault-Heartbeat/1.0 (self-check; +https://digivault.digilatics.co/bot)',
			) );
			if ( ! is_wp_error( $response ) ) {
				$status = (int) wp_remote_retrieve_response_code( $response );
				$ms     = (int) round( ( microtime( true ) - $start ) * 1000 );
			}
		} catch ( Exception $e ) {
			$status = null;
		} catch ( Error $e ) {
			$status = null;
		}
		return array( 'loopback_status' => $status ?: null, 'loopback_ms' => $ms );
	}
}

if ( ! function_exists( 'dvc2_cron_tick' ) ) {
	function dvc2_cron_tick() {
		// Past the dead-man switch nobody is listening: stop the loopback too.
		$beat = dvc2_is_active() ? dvc2_heartbeat() : null;
		dvc2_flush( null, $beat );
	}
}

/**
 * Cron safety net and heartbeat. A low-traffic site may not fire enough
 * shutdowns to matter; a high-traffic one must not flush on every request.
 * WP-cron is itself traffic-driven, which matches how the rest of Stacks Monitor
 * collects -- so a silent heartbeat is never read as "down", only a fresh one
 * as "up".
 */
add_action( 'dvc2_cron_flush', 'dvc2_cron_tick' );
add_filter( 'cron_schedules', function ( $schedules ) {
	$schedules['dvc2_five_minutes'] = array( 'interval' => 300, 'display' => 'Every 5 minutes' );
	return $schedules;
} );
add_action( 'init', function () {
	if ( ! wp_next_scheduled( 'dvc2_cron_flush' ) ) {
		wp_schedule_event( time() + 300, 'dvc2_five_minutes', 'dvc2_cron_flush' );
	}
} );

/* ---------------------------------------------------------------------------
 * Hooks. Every callback is a thin call into dvc2_record, which swallows its own
 * failures -- a collector fault must never break the client's site.
 * ------------------------------------------------------------------------- */

add_action( 'wp_login', function ( $login, $user ) {
	dvc2_record( 'login', sprintf( '%s logged in', $login ), array(), 'user', $user ? $user->ID : '' );
}, 10, 2 );

add_action( 'wp_login_failed', function ( $login ) {
	dvc2_record( 'login_failed', sprintf( 'Failed login for %s', $login ), array(), 'user', '' );
} );

add_action( 'user_register', function ( $user_id ) {
	$user = get_userdata( $user_id );
	$role = ( $user && ! empty( $user->roles ) ) ? $user->roles[0] : '';
	dvc2_record( 'user_created',
		sprintf( 'User %s created (%s)', $user ? $user->user_login : $user_id, $role ),
		array( 'role' => $role ), 'user', $user_id );
} );

add_action( 'profile_update', function ( $user_id ) {
	$user = get_userdata( $user_id );
	dvc2_record( 'user_updated',
		sprintf( 'User %s updated', $user ? $user->user_login : $user_id ),
		array(), 'user', $user_id );
} );

add_action( 'set_user_role', function ( $user_id, $role, $old_roles ) {
	$user = get_userdata( $user_id );
	dvc2_record( 'user_role_changed',
		sprintf( 'User %s role changed to %s', $user ? $user->user_login : $user_id, $role ),
		array( 'new_role' => $role, 'old_role' => ( is_array( $old_roles ) && $old_roles ) ? $old_roles[0] : '' ),
		'user', $user_id );
}, 10, 3 );

add_action( 'delete_user', function ( $user_id ) {
	$user = get_userdata( $user_id );
	dvc2_record( 'user_deleted',
		sprintf( 'User %s deleted', $user ? $user->user_login : $user_id ),
		array(), 'user', $user_id );
} );

add_action( 'password_reset', function ( $user ) {
	dvc2_record( 'password_reset', sprintf( 'Password reset for %s', $user->user_login ),
		array(), 'user', $user->ID );
} );

add_action( 'activated_plugin', function ( $plugin ) {
	dvc2_record( 'plugin_activated', sprintf( 'Plugin %s activated', $plugin ),
		array( 'slug' => $plugin ), 'plugin', $plugin );
} );

add_action( 'deactivated_plugin', function ( $plugin ) {
	dvc2_record( 'plugin_deactivated', sprintf( 'Plugin %s deactivated', $plugin ),
		array( 'slug' => $plugin ), 'plugin', $plugin );
} );

add_action( 'deleted_plugin', function ( $plugin ) {
	dvc2_record( 'plugin_deleted', sprintf( 'Plugin %s deleted', $plugin ),
		array( 'slug' => $plugin ), 'plugin', $plugin );
} );

add_action( 'switch_theme', function ( $name, $theme ) {
	dvc2_record( 'theme_switched', sprintf( 'Theme switched to %s', $name ),
		array( 'name' => $name, 'version' => $theme ? $theme->get( 'Version' ) : '' ), 'theme', $name );
}, 10, 2 );

add_action( 'deleted_theme', function ( $stylesheet ) {
	dvc2_record( 'theme_deleted', sprintf( 'Theme %s deleted', $stylesheet ),
		array( 'slug' => $stylesheet ), 'theme', $stylesheet );
} );

add_action( 'upgrader_process_complete', function ( $upgrader, $extra ) {
	$type = isset( $extra['type'] ) ? $extra['type'] : '';
	if ( 'plugin' === $type ) {
		$slugs = isset( $extra['plugins'] ) ? $extra['plugins'] : array();
		foreach ( (array) $slugs as $slug ) {
			dvc2_record( 'plugin_updated', sprintf( 'Plugin %s updated', $slug ),
				array( 'slug' => $slug ), 'plugin', $slug );
		}
	} elseif ( 'theme' === $type ) {
		$slugs = isset( $extra['themes'] ) ? $extra['themes'] : array();
		foreach ( (array) $slugs as $slug ) {
			dvc2_record( 'theme_updated', sprintf( 'Theme %s updated', $slug ),
				array( 'slug' => $slug ), 'theme', $slug );
		}
	} elseif ( 'core' === $type ) {
		dvc2_record( 'core_updated', 'WordPress core updated',
			array( 'version' => get_bloginfo( 'version' ) ), 'core', 'wordpress' );
	}
}, 10, 2 );

add_action( 'transition_post_status', function ( $new, $old, $post ) {
	if ( ! in_array( $post->post_type, array( 'post', 'page' ), true ) ) { return; }
	if ( 'auto-draft' === $post->post_status || 'auto-draft' === $old ) { return; }
	if ( $new === $old ) { return; }
	if ( 'trash' === $new ) {
		dvc2_record( 'post_trashed', sprintf( 'Trashed: %s', $post->post_title ),
			array( 'post_type' => $post->post_type ), $post->post_type, $post->ID );
	} elseif ( 'publish' === $new && 'publish' !== $old ) {
		dvc2_record( 'post_published', sprintf( 'Published: %s', $post->post_title ),
			array( 'post_type' => $post->post_type ), $post->post_type, $post->ID );
	} elseif ( 'publish' === $new ) {
		dvc2_record( 'post_updated', sprintf( 'Updated: %s', $post->post_title ),
			array( 'post_type' => $post->post_type ), $post->post_type, $post->ID );
	}
}, 10, 3 );

add_action( 'before_delete_post', function ( $post_id ) {
	$post = get_post( $post_id );
	if ( ! $post || ! in_array( $post->post_type, array( 'post', 'page' ), true ) ) { return; }
	dvc2_record( 'post_deleted', sprintf( 'Deleted: %s', $post->post_title ),
		array( 'post_type' => $post->post_type ), $post->post_type, $post_id );
} );

add_action( 'woocommerce_order_status_changed', function ( $order_id, $from, $to ) {
	dvc2_record( 'order_status_changed', sprintf( 'Order #%s: %s to %s', $order_id, $from, $to ),
		array( 'old_status' => $from, 'new_status' => $to, 'order_id' => $order_id ), 'order', $order_id );
}, 10, 3 );

add_action( 'woocommerce_update_product', function ( $product_id ) {
	dvc2_record( 'product_updated', sprintf( 'Product #%s updated', $product_id ),
		array(), 'product', $product_id );
} );

add_action( 'woocommerce_order_refunded', function ( $order_id, $refund_id ) {
	dvc2_record( 'order_refunded', sprintf( 'Order #%s refunded', $order_id ),
		array( 'order_id' => $order_id ), 'order', $order_id );
}, 10, 2 );

/** Files above this are not code, and hashing them wastes the tick. */
define( 'DVC2_MAX_FILE_BYTES', 2097152 );
define( 'DVC2_WALK_SLICE',     400 );

/**
 * One slice of the daily wp-content walk.
 *
 * Chunked with a cursor because a 50k-file site cannot be walked inside a
 * single cron tick. No baseline is kept here -- Stacks Monitor holds it and diffs.
 * Storing a checksum table on the client would be the database bloat MalCare
 * markets against, and the diff belongs in Python where it can be tested.
 */
if ( ! function_exists( 'dvc2_walk' ) ) {
	function dvc2_walk() {
		try {
			if ( ! dvc2_is_active() ) { return; }

			$walk_id = get_option( 'dvc2_walk_id', '' );
			$cursor  = (int) get_option( 'dvc2_walk_cursor', 0 );
			if ( '' === $walk_id ) {
				$walk_id = uniqid( 'w', true );
				$cursor  = 0;
				update_option( 'dvc2_walk_id', $walk_id, false );
			}

			$roots = array(
				WP_CONTENT_DIR . '/plugins',
				WP_CONTENT_DIR . '/themes',
				WP_CONTENT_DIR . '/mu-plugins',
			);

			$paths = array();
			foreach ( $roots as $root ) {
				if ( ! is_dir( $root ) ) { continue; }
				$iterator = new RecursiveIteratorIterator(
					new RecursiveDirectoryIterator( $root, FilesystemIterator::SKIP_DOTS ),
					RecursiveIteratorIterator::LEAVES_ONLY
				);
				foreach ( $iterator as $file ) {
					if ( ! $file->isFile() ) { continue; }
					$ext = strtolower( $file->getExtension() );
					if ( ! in_array( $ext, array( 'php', 'js', 'htaccess' ), true ) ) { continue; }
					if ( $file->getSize() > DVC2_MAX_FILE_BYTES ) { continue; }
					$paths[] = $file->getPathname();
				}
			}
			sort( $paths );

			$slice   = array_slice( $paths, $cursor, DVC2_WALK_SLICE );
			$entries = array();
			foreach ( $slice as $path ) {
				$hash = @md5_file( $path );
				if ( false === $hash ) { continue; }
				$rel = ltrim( str_replace( WP_CONTENT_DIR, '', $path ), '/\\' );
				$entries[ $rel ] = $hash;
			}

			$next     = $cursor + DVC2_WALK_SLICE;
			$complete = $next >= count( $paths );

			update_option( 'dvc2_pending_manifest', array(
				'walk_id'  => $walk_id,
				'entries'  => $entries,
				'complete' => $complete,
			), false );

			if ( $complete ) {
				delete_option( 'dvc2_walk_id' );
				update_option( 'dvc2_walk_cursor', 0, false );
			} else {
				update_option( 'dvc2_walk_cursor', $next, false );
			}

			dvc2_flush();
		} catch ( Exception $e ) {
			return;
		} catch ( Error $e ) {
			return;
		}
	}
}

add_action( 'dvc2_cron_walk', 'dvc2_walk' );
add_action( 'init', function () {
	if ( ! wp_next_scheduled( 'dvc2_cron_walk' ) ) {
		wp_schedule_event( time() + 3600, 'daily', 'dvc2_cron_walk' );
	}
} );
"""


def build_wp_sso_snippet(secret: str, site_id: str = "", ingest_url: str = "") -> str:
    """Return the ready-to-paste PHP snippet with per-site values baked in."""
    if not secret:
        return ""
    return (
        _TEMPLATE
        .replace("__DVC_SECRET__", secret)
        .replace("__DVC_SITE_ID__", site_id)
        .replace("__DVC_INGEST_URL__", ingest_url)
    )
