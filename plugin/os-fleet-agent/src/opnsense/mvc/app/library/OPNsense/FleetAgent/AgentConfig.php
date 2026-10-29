<?php

namespace OPNsense\FleetAgent;

use OPNsense\Core\Config;

/**
 * Typed access to the OFME settings model.
 *
 * All values are read through string casts because the OPNsense model
 * framework returns field objects. Methods clamp intervals and timeouts so a
 * malformed config.xml cannot make the daemon spin or hang.
 */
final class AgentConfig
{
    private Settings $model;

    public function __construct(?Settings $model = null)
    {
        $this->model = $model ?? new Settings();
    }

    public function model(): Settings
    {
        return $this->model;
    }

    private function value(string $name, string $default = ''): string
    {
        if (!isset($this->model->{$name})) {
            return $default;
        }
        $value = (string)$this->model->{$name};
        return $value;
    }

    public function enabled(): bool
    {
        return $this->value('enabled', '0') === '1';
    }

    public function platformUrl(): string
    {
        return rtrim(trim($this->value('platform_url')), '/');
    }

    /**
     * Platform API root including /api/v1. A URL that already ends with the
     * version suffix is accepted and not duplicated.
     */
    public function apiBase(): string
    {
        $base = $this->platformUrl();
        if ($base === '') {
            return '';
        }
        if (preg_match('~/api/v1$~i', $base)) {
            return $base;
        }
        return $base . '/api/v1';
    }

    public function enrollmentToken(): string
    {
        return trim($this->value('enrollment_token'));
    }

    public function deviceId(): string
    {
        return trim($this->value('device_id'));
    }

    public function deviceName(): string
    {
        return trim($this->value('device_name'));
    }

    public function certificateSerial(): string
    {
        return trim($this->value('certificate_serial'));
    }

    public function caFingerprint(): string
    {
        return trim($this->value('ca_fingerprint'));
    }

    public function heartbeatUrl(): string
    {
        $url = trim($this->value('heartbeat_url'));
        if ($url !== '') {
            return $url;
        }
        return $this->apiBase() . '/agent/heartbeat';
    }

    public function heartbeatInterval(): int
    {
        return $this->intValue('heartbeat_interval', 60, 15, 3600);
    }

    public function configInterval(): int
    {
        return $this->intValue('config_interval', 300, 60, 86400);
    }

    public function renewBeforeDays(): int
    {
        return $this->intValue('renew_before_days', 30, 1, 365);
    }

    public function requestTimeout(): int
    {
        return $this->intValue('request_timeout', 20, 5, 120);
    }

    public function verifyTls(): bool
    {
        return $this->value('verify_tls', '1') === '1';
    }

    public function proxyUrl(): string
    {
        return trim($this->value('proxy_url'));
    }

    public function applyAliases(): bool
    {
        return $this->value('apply_aliases', '0') === '1';
    }

    public function applyFirewallRules(): bool
    {
        return $this->value('apply_firewall_rules', '0') === '1';
    }

    public function logLevel(): string
    {
        $level = strtolower($this->value('log_level', 'info'));
        return in_array($level, ['debug', 'info', 'warning'], true) ? $level : 'info';
    }

    public function lastSeen(): string
    {
        return $this->value('last_seen');
    }

    public function lastConfigHash(): string
    {
        return $this->value('last_config_hash');
    }

    /**
     * TLS and transport options for HttpClient.
     *
     * @return array<string, mixed>
     */
    public function transportOptions(bool $withIdentity = true): array
    {
        return [
            'verify' => $this->verifyTls(),
            'ca_file' => is_file(Paths::CA_FILE) ? Paths::CA_FILE : null,
            'cert_file' => $withIdentity && is_file(Paths::CERT_FILE) ? Paths::CERT_FILE : null,
            'key_file' => $withIdentity && is_file(Paths::KEY_FILE) ? Paths::KEY_FILE : null,
            'proxy' => $this->proxyUrl(),
            'timeout' => $this->requestTimeout(),
            'user_agent' => 'os-fleet-agent/' . Paths::VERSION,
        ];
    }

    /**
     * Persist changes to config.xml.
     */
    public function save(): void
    {
        $this->model->serializeToConfig();
        Config::getInstance()->save();
    }

    /**
     * Update model fields from a validated associative array.
     *
     * @param array<string, mixed> $values
     */
    public function update(array $values): void
    {
        $editable = [
            'enabled',
            'platform_url',
            'enrollment_token',
            'heartbeat_interval',
            'config_interval',
            'renew_before_days',
            'request_timeout',
            'verify_tls',
            'proxy_url',
            'apply_aliases',
            'apply_firewall_rules',
            'log_level',
        ];
        foreach ($editable as $field) {
            if (!array_key_exists($field, $values)) {
                continue;
            }
            $value = $values[$field];
            if (is_bool($value)) {
                $value = $value ? '1' : '0';
            }
            $this->model->{$field} = (string)$value;
        }
    }

    /**
     * Store the result of a successful enrollment and discard the one-time token.
     *
     * @param array<string, mixed> $result
     */
    public function applyEnrollment(array $result): void
    {
        $this->model->device_id = (string)($result['device_id'] ?? '');
        $this->model->device_name = (string)($result['device_name'] ?? '');
        $this->model->certificate_serial = (string)($result['certificate_serial'] ?? '');
        $this->model->ca_fingerprint = (string)($result['ca_fingerprint'] ?? '');
        $this->model->heartbeat_url = (string)($result['heartbeat_url'] ?? '');
        $interval = (int)($result['heartbeat_interval_seconds'] ?? 60);
        $this->model->heartbeat_interval = (string)max(15, min($interval, 3600));
        $this->model->enrollment_token = '';
        $this->save();
    }

    public function clearEnrollmentToken(): void
    {
        $this->model->enrollment_token = '';
        $this->save();
    }

    /**
     * Non-secret settings, suitable for the status API.
     *
     * @return array<string, mixed>
     */
    public function export(): array
    {
        return [
            'enabled' => $this->enabled(),
            'platform_url' => $this->platformUrl(),
            'device_id' => $this->deviceId(),
            'device_name' => $this->deviceName(),
            'certificate_serial' => $this->certificateSerial(),
            'ca_fingerprint' => $this->caFingerprint(),
            'heartbeat_url' => $this->heartbeatUrl(),
            'heartbeat_interval' => $this->heartbeatInterval(),
            'config_interval' => $this->configInterval(),
            'renew_before_days' => $this->renewBeforeDays(),
            'request_timeout' => $this->requestTimeout(),
            'verify_tls' => $this->verifyTls(),
            'proxy_url' => $this->proxyUrl(),
            'apply_aliases' => $this->applyAliases(),
            'apply_firewall_rules' => $this->applyFirewallRules(),
            'log_level' => $this->logLevel(),
            'has_enrollment_token' => $this->enrollmentToken() !== '',
            'last_seen' => $this->lastSeen(),
            'last_config_hash' => $this->lastConfigHash(),
        ];
    }

    /**
     * Update metadata after a successful heartbeat.
     */
    public function recordHeartbeat(string $timestamp, ?string $configHash = null): void
    {
        $this->model->last_seen = $timestamp;
        if ($configHash !== null && $configHash !== '') {
            $this->model->last_config_hash = $configHash;
        }
        $this->save();
    }

    /**
     * Write an imported PEM bundle as the pinned platform CA.
     */
    public function importCa(string $pem): string
    {
        $pem = trim($pem);
        if ($pem === '') {
            throw new \InvalidArgumentException('The CA bundle is empty.');
        }
        $certificate = @openssl_x509_read($pem);
        if ($certificate === false) {
            throw new \InvalidArgumentException('The supplied data is not a valid PEM certificate.');
        }
        $fingerprint = @openssl_x509_fingerprint($pem, 'sha256');
        if ($fingerprint === false) {
            throw new \InvalidArgumentException('Unable to compute the CA fingerprint.');
        }
        $normalised = strtolower(str_replace([':', ' '], '', $fingerprint));
        Paths::write(Paths::CA_FILE, $pem . PHP_EOL, 0644);
        $this->model->ca_fingerprint = $normalised;
        $this->save();
        return $normalised;
    }

    private function intValue(string $name, int $default, int $minimum, int $maximum): int
    {
        $raw = $this->value($name, (string)$default);
        $value = ctype_digit($raw) ? (int)$raw : $default;
        return max($minimum, min($value, $maximum));
    }
}
