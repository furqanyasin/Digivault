<?php
/**
 * Uninstall handler — removes stored options. Provisioned WP users are kept
 * (removing accounts on plugin deletion would be destructive).
 *
 * @package Digivault_Connect
 */

defined( 'WP_UNINSTALL_PLUGIN' ) || exit;

delete_option( 'dvc_settings' );
