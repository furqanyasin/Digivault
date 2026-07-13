<?php
/**
 * Settings page — stores the shared secret used to verify Digivault SSO tokens.
 *
 * @package Digivault_Connect
 */

defined( 'ABSPATH' ) || exit;

/**
 * Registers the settings page under Settings → Digivault Connect.
 */
class Digivault_Connect_Settings {

	const OPTION_NAME = 'dvc_settings';

	/**
	 * Hook everything up.
	 */
	public function __construct() {
		add_action( 'admin_menu', array( $this, 'add_settings_page' ) );
		add_action( 'admin_init', array( $this, 'register_settings' ) );
	}

	/**
	 * The stored shared secret ('' when unconfigured).
	 *
	 * @return string
	 */
	public static function get_secret() {
		$settings = get_option( self::OPTION_NAME, array() );
		return isset( $settings['shared_secret'] ) ? (string) $settings['shared_secret'] : '';
	}

	/**
	 * Add the options page.
	 *
	 * @return void
	 */
	public function add_settings_page() {
		add_options_page(
			__( 'Digivault Connect', 'digivault-connect' ),
			__( 'Digivault Connect', 'digivault-connect' ),
			'manage_options',
			'digivault-connect',
			array( $this, 'render_settings_page' )
		);
	}

	/**
	 * Register the option + fields.
	 *
	 * @return void
	 */
	public function register_settings() {
		register_setting(
			'dvc_settings_group',
			self::OPTION_NAME,
			array(
				'type'              => 'array',
				'sanitize_callback' => array( $this, 'sanitize_settings' ),
				'default'           => array(),
			)
		);

		add_settings_section(
			'dvc_main_section',
			__( 'Single Sign-On', 'digivault-connect' ),
			array( $this, 'render_section_intro' ),
			'digivault-connect'
		);

		add_settings_field(
			'dvc_shared_secret',
			__( 'Shared secret', 'digivault-connect' ),
			array( $this, 'render_secret_field' ),
			'digivault-connect',
			'dvc_main_section'
		);
	}

	/**
	 * Sanitize submitted settings.
	 *
	 * @param array $input Raw settings array.
	 * @return array
	 */
	public function sanitize_settings( $input ) {
		$clean = array();
		if ( isset( $input['shared_secret'] ) ) {
			// Secrets are URL-safe base64 — restrict to that alphabet.
			$clean['shared_secret'] = preg_replace(
				'/[^A-Za-z0-9_\-]/',
				'',
				sanitize_text_field( wp_unslash( $input['shared_secret'] ) )
			);
		}
		return $clean;
	}

	/**
	 * Section intro copy.
	 *
	 * @return void
	 */
	public function render_section_intro() {
		echo '<p>' . esc_html__(
			'Paste the shared secret generated for this website in the Digivault dashboard (website → Access tab → WP Admin login). Digivault signs each login link with this secret; links are single-use and expire after two minutes.',
			'digivault-connect'
		) . '</p>';
	}

	/**
	 * Secret input field.
	 *
	 * @return void
	 */
	public function render_secret_field() {
		printf(
			'<input type="password" class="regular-text" name="%s[shared_secret]" value="%s" autocomplete="off" />',
			esc_attr( self::OPTION_NAME ),
			esc_attr( self::get_secret() )
		);
	}

	/**
	 * Render the settings page.
	 *
	 * @return void
	 */
	public function render_settings_page() {
		if ( ! current_user_can( 'manage_options' ) ) {
			return;
		}
		?>
		<div class="wrap">
			<h1><?php esc_html_e( 'Digivault Connect', 'digivault-connect' ); ?></h1>
			<form method="post" action="options.php">
				<?php
				settings_fields( 'dvc_settings_group' );
				do_settings_sections( 'digivault-connect' );
				submit_button();
				?>
			</form>
			<p class="description">
				<?php
				printf(
					/* translators: %s: REST endpoint URL. */
					esc_html__( 'SSO endpoint: %s', 'digivault-connect' ),
					esc_html( rest_url( 'digivault/v1/sso' ) )
				);
				?>
			</p>
		</div>
		<?php
	}
}
