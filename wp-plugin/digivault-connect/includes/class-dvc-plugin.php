<?php
/**
 * Main plugin class — wires up admin settings and the REST controller.
 *
 * @package Digivault_Connect
 */

defined( 'ABSPATH' ) || exit;

/**
 * Singleton wiring class.
 */
class Digivault_Connect_Plugin {

	/**
	 * Singleton instance.
	 *
	 * @var Digivault_Connect_Plugin|null
	 */
	private static $instance = null;

	/**
	 * Settings module.
	 *
	 * @var Digivault_Connect_Settings
	 */
	public $settings;

	/**
	 * REST controller module.
	 *
	 * @var Digivault_Connect_Rest_Controller
	 */
	public $rest;

	/**
	 * Get the singleton instance.
	 *
	 * @return Digivault_Connect_Plugin
	 */
	public static function instance() {
		if ( null === self::$instance ) {
			self::$instance = new self();
		}
		return self::$instance;
	}

	/**
	 * Instantiate modules.
	 */
	private function __construct() {
		$this->settings = new Digivault_Connect_Settings();
		$this->rest     = new Digivault_Connect_Rest_Controller();
	}
}
