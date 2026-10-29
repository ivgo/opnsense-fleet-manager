<?php

namespace OPNsense\FleetAgent;

/**
 * Bootstrap and enrollment workflow.
 *
 * The one-time token is intentionally cleared from config.xml after a
 * successful enrollment. The private key is only persisted after the platform
 * has returned a certificate that matches it and validates against the
 * returned CA.
 */
final class Enrollment
{
    public function __construct(private AgentConfig $config)
    {
    }

    /**
     * @return array<string, mixed>
     */
    public function bootstrap(string $token): array
    {
        $token = trim($token);
        if (strlen($token) < 16) {
            throw new \InvalidArgumentException('The enrollment token must be at least 16 characters.');
        }

        $client = new HttpClient($this->config->apiBase(), $this->config->transportOptions(false));
        $response = $client->get('/agent/bootstrap', ['token' => $token]);
        if ($response['status'] !== 200 || !is_array($response['json'])) {
            throw new \RuntimeException('Bootstrap failed: ' . $this->describe($response));
        }

        $package = $response['json'];
        State::merge([
            'bootstrap' => $package,
            'bootstrap_at' => gmdate('c'),
        ]);
        Logger::info('Enrollment bootstrap retrieved', [
            'enrollment_id' => $package['enrollment_id'] ?? null,
            'device_name' => $package['device_name'] ?? null,
        ]);
        return $package;
    }

    /**
     * @return array<string, mixed>
     */
    public function enroll(string $token): array
    {
        $token = trim($token);
        if ($token === '') {
            throw new \InvalidArgumentException('No enrollment token is configured.');
        }

        $bootstrap = $this->bootstrap($token);
        $identity = new Identity();
        $commonName = $identity->commonName();
        $keys = $identity->generateKeyPair($commonName);

        $payload = [
            'token' => $token,
            'serial_number' => $identity->serialNumber(),
            'mac_address' => $identity->macAddress(),
            'hostname' => $identity->hostname(),
            'model' => $identity->model(),
            'firmware_version' => $identity->firmwareVersion(),
            'csr_pem' => $keys['csr_pem'],
            'hardware_profile' => $identity->hardwareProfile(),
        ];

        $client = new HttpClient($this->config->apiBase(), $this->config->transportOptions(false));
        $response = $client->post('/agent/enroll', $payload);
        if (!in_array($response['status'], [200, 201], true) || !is_array($response['json'])) {
            throw new \RuntimeException('Enrollment failed: ' . $this->describe($response));
        }

        $data = $response['json'];
        foreach (['device_id', 'certificate_pem', 'ca_pem', 'certificate_serial', 'heartbeat_url'] as $field) {
            if (empty($data[$field]) || !is_string($data[$field])) {
                throw new \RuntimeException(sprintf('The platform response is missing %s.', $field));
            }
        }

        $identity->writePrivateKey($keys['key_pem']);
        try {
            $certificate = $identity->installCertificate($data['certificate_pem'], $data['ca_pem']);
        } catch (\Throwable $exception) {
            Paths::delete(Paths::KEY_FILE);
            throw $exception;
        }

        $expectedCa = $this->normaliseFingerprint(
            (string)($bootstrap['platform']['ca_fingerprint'] ?? '')
        );
        $actualCa = (string)$identity->caFingerprint();
        if ($expectedCa !== '' && $actualCa !== '' && $expectedCa !== $actualCa) {
            Paths::reset();
            throw new \RuntimeException('The enrollment CA does not match the fingerprint advertised by the platform.');
        }

        $heartbeatUrl = (string)$data['heartbeat_url'];
        if (!preg_match('~^https?://~i', $heartbeatUrl)) {
            $heartbeatUrl = $this->config->apiBase() . '/' . ltrim($heartbeatUrl, '/');
        }

        $this->config->applyEnrollment([
            'device_id' => (string)$data['device_id'],
            'device_name' => (string)($data['device_name'] ?? $bootstrap['device_name'] ?? ''),
            'certificate_serial' => (string)$data['certificate_serial'],
            'ca_fingerprint' => $actualCa,
            'heartbeat_url' => $heartbeatUrl,
            'heartbeat_interval_seconds' => (int)($data['heartbeat_interval_seconds'] ?? 60),
        ]);

        State::merge([
            'enrolled_at' => gmdate('c'),
            'device_id' => (string)$data['device_id'],
            'device_name' => (string)($data['device_name'] ?? ''),
            'certificate_serial' => (string)$data['certificate_serial'],
            'heartbeat_url' => $heartbeatUrl,
            'last_error' => null,
            'last_error_at' => null,
            'consecutive_failures' => 0,
        ]);

        Logger::info('Device enrolled', [
            'device_id' => $data['device_id'],
            'device_name' => $data['device_name'] ?? null,
            'certificate_serial' => $data['certificate_serial'],
            'ca_fingerprint' => $actualCa,
        ]);

        return [
            'status' => 'enrolled',
            'device_id' => (string)$data['device_id'],
            'device_name' => (string)($data['device_name'] ?? ''),
            'certificate_serial' => (string)$data['certificate_serial'],
            'certificate' => $certificate,
            'ca_fingerprint' => $actualCa,
            'heartbeat_url' => $heartbeatUrl,
            'heartbeat_interval_seconds' => (int)($data['heartbeat_interval_seconds'] ?? 60),
            'bootstrap' => $bootstrap,
        ];
    }

    /**
     * Extract a useful error message from a platform response.
     *
     * @param array<string, mixed> $response
     */
    public function describe(array $response): string
    {
        $json = $response['json'] ?? null;
        if (is_array($json)) {
            if (isset($json['error']['message']) && is_string($json['error']['message'])) {
                return $json['error']['message'];
            }
            if (isset($json['detail'])) {
                if (is_string($json['detail'])) {
                    return $json['detail'];
                }
                $encoded = json_encode($json['detail'], JSON_UNESCAPED_SLASHES);
                if ($encoded !== false) {
                    return $encoded;
                }
            }
            if (isset($json['message']) && is_string($json['message'])) {
                return $json['message'];
            }
        }

        $body = trim((string)($response['body'] ?? ''));
        if ($body !== '') {
            return substr($body, 0, 500);
        }
        if (!empty($response['error'])) {
            return (string)$response['error'];
        }
        return 'HTTP ' . (int)($response['status'] ?? 0);
    }

    private function normaliseFingerprint(string $value): string
    {
        return strtolower(str_replace([':', ' '], '', trim($value)));
    }
}
