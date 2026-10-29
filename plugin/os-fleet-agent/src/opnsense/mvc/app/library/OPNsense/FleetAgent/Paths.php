<?php

namespace OPNsense\FleetAgent;

/**
 * Filesystem layout for the OFME Fleet Agent.
 *
 * Certificate material is kept outside config.xml so that a configuration
 * backup does not expose the device private key. The configuration directory
 * is root-only (0700) and every file written through this class is 0600.
 */
final class Paths
{
    public const VERSION = '1.0.0';

    public const CONFIG_DIR = '/usr/local/etc/ofme-agent';
    public const KEY_FILE = self::CONFIG_DIR . '/device.key';
    public const CERT_FILE = self::CONFIG_DIR . '/device.crt';
    public const CA_FILE = self::CONFIG_DIR . '/ca.crt';
    public const CSR_FILE = self::CONFIG_DIR . '/device.csr';
    public const STATE_FILE = self::CONFIG_DIR . '/state.json';
    public const MANAGED_FILE = self::CONFIG_DIR . '/managed.json';
    public const DESIRED_FILE = self::CONFIG_DIR . '/desired.json';
    public const APPLY_FILE = self::CONFIG_DIR . '/apply-report.json';
    public const DIAGNOSTICS_DIR = self::CONFIG_DIR . '/diagnostics';

    public const LOG_FILE = '/var/log/ofme-agent.log';
    public const LOCK_FILE = '/var/run/ofme-agent.lock';
    public const PID_FILE = '/var/run/os_fleet_agent.pid';

    public const CONFIGD = '/usr/local/sbin/configctl';
    public const PHP = '/usr/local/bin/php';
    public const AGENT_SCRIPT = '/usr/local/opnsense/scripts/OPNsense/FleetAgent/agent.php';
    public const RC_SCRIPT = '/usr/local/etc/rc.d/os-fleet-agent';

    public const MAX_LOG_BYTES = 5242880;

    /**
     * Create the configuration directory with restrictive permissions.
     */
    public static function ensure(): void
    {
        if (!is_dir(self::CONFIG_DIR)) {
            @mkdir(self::CONFIG_DIR, 0700, true);
        }
        @chmod(self::CONFIG_DIR, 0700);

        if (!is_dir(self::DIAGNOSTICS_DIR)) {
            @mkdir(self::DIAGNOSTICS_DIR, 0700, true);
        }
        @chmod(self::DIAGNOSTICS_DIR, 0700);
    }

    /**
     * Atomically write a file with the requested mode.
     */
    public static function write(string $path, string $contents, int $mode = 0600): void
    {
        self::ensure();
        $directory = dirname($path);
        if (!is_dir($directory)) {
            @mkdir($directory, 0700, true);
            @chmod($directory, 0700);
        }

        $temporary = @tempnam($directory, '.ofme-');
        if ($temporary === false) {
            throw new \RuntimeException(sprintf('Unable to create a temporary file in %s', $directory));
        }

        try {
            if (@file_put_contents($temporary, $contents) === false) {
                throw new \RuntimeException(sprintf('Unable to write %s', $path));
            }
            @chmod($temporary, $mode);
            if (!@rename($temporary, $path)) {
                throw new \RuntimeException(sprintf('Unable to replace %s', $path));
            }
            @chmod($path, $mode);
        } finally {
            if (is_file($temporary)) {
                @unlink($temporary);
            }
        }
    }

    public static function read(string $path): ?string
    {
        if (!is_file($path) || !is_readable($path)) {
            return null;
        }
        $contents = @file_get_contents($path);
        return $contents === false ? null : $contents;
    }

    public static function delete(string $path): void
    {
        if (is_file($path) || is_link($path)) {
            @unlink($path);
        }
    }

    public static function isEnrolled(): bool
    {
        foreach ([self::KEY_FILE, self::CERT_FILE, self::CA_FILE] as $file) {
            if (!is_file($file) || filesize($file) === 0) {
                return false;
            }
        }
        return true;
    }

    /**
     * SHA-256 fingerprint of a PEM certificate file, lowercase hex.
     */
    public static function fingerprintFromFile(string $path): ?string
    {
        $pem = self::read($path);
        if ($pem === null || $pem === '') {
            return null;
        }
        $fingerprint = @openssl_x509_fingerprint($pem, 'sha256');
        if ($fingerprint === false) {
            return null;
        }
        return strtolower(str_replace([':', ' '], '', $fingerprint));
    }

    /**
     * Remove enrollment material and transient state, keeping configuration.
     */
    public static function reset(): void
    {
        foreach (
            [
                self::KEY_FILE,
                self::CERT_FILE,
                self::CA_FILE,
                self::CSR_FILE,
                self::STATE_FILE,
                self::MANAGED_FILE,
                self::DESIRED_FILE,
                self::APPLY_FILE,
            ] as $file
        ) {
            self::delete($file);
        }
        foreach (glob(self::DIAGNOSTICS_DIR . '/*.json') ?: [] as $file) {
            self::delete($file);
        }
    }

    /**
     * Probe whether a PID file points at a live process.
     */
    public static function serviceRunning(): bool
    {
        $pid = self::read(self::PID_FILE);
        if ($pid === null) {
            return false;
        }
        $pid = trim($pid);
        if ($pid === '' || !ctype_digit($pid)) {
            return false;
        }
        return @posix_kill((int)$pid, 0);
    }
}
