<?php
/**
 * Plugin Name:       Digivault Connect
 * Plugin URI:        https://digivault.digilatics.co
 * Description:       One-click, role-mapped login into wp-admin from the Digivault dashboard via HMAC-signed one-time tokens. No shared passwords.
 * Version:           1.0.0
 * Requires at least: 6.0
 * Requires PHP:      7.4
 * Author:            Digilatics
 * Author URI:        https://digilatics.co
 * License:           GPL v2 or later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       digivault-connect
 *
 * @package Digivault_Connect
 */

defined( 'ABSPATH' ) || exit;

define( 'DVC_VERSION', '1.0.0' );
define( 'DVC_PLUGIN_DIR', plugin_dir_path( __FILE__ ) );
define( 'DVC_PLUGIN_URL', plugin_dir_url( __FILE__ ) );
define( 'DVC_PLUGIN_BASENAME', plugin_basename( __FILE__ ) );

require_once DVC_PLUGIN_DIR . 'includes/class-dvc-plugin.php';
require_once DVC_PLUGIN_DIR . 'admin/class-dvc-settings.php';
require_once DVC_PLUGIN_DIR . 'api/class-dvc-rest-controller.php';

/**
 * Boot the plugin.
 *
 * @return void
 */
function dvc_init() {
	Digivault_Connect_Plugin::instance();
}
add_action( 'plugins_loaded', 'dvc_init' );
