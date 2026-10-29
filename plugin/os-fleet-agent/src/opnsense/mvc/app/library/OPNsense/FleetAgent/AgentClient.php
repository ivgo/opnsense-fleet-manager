<?php

namespace OPNsense\FleetAgent;

/**
 * Authenticated client for the OFME device API.
 *
 * Every request carries the device identifier and the SHA-256 fingerprint of
 * the installed device certificate. The serial number is included as a
 * development-only fallback for platforms that do not terminate mTLS.
 */
final class AgentClient
{
    public function __construct(private AgentConfig $config, private Identity $identity)
    {
    }

    public function platform(bool $withIdentity = true): HttpClient
    {
        $options = $this->config->transportOptions($withIdentity);

        if ($withIdentity && $this->config->deviceId() !== '') {
            $headers = ['X-Device-Id: ' . $this->config->deviceId()];
            $fingerprint = $this->identity->fingerprint();
            if ($fingerprint !== null && $fingerprint !== '') {
                $headers[] = 'X-Device-Cert-Fingerprint: ' . $fingerprint;
            }
            $serial = $this->identity->serialNumber();
            if ($serial !== '') {
                $headers[] = 'X-Device-Serial: ' . $serial;
            }
            $options['headers'] = $headers;
        }

        return new HttpClient($this->config->apiBase(), $options);
    }

    /**
     * @param array<string, mixed> $payload
     * @return array<string, mixed>
     */
    public function heartbeat(array $payload): array
    {
        return $this->platform()->post($this->config->heartbeatUrl(), $payload);
    }

    /**
     * @return array<string, mixed>
     */
    public function desiredConfig(): array
    {
        return $this->platform()->get('/agent/config');
    }

    /**
     * @return array<string, mixed>
     */
    public function commands(): array
    {
        return $this->platform()->get('/agent/commands');
    }

    /**
     * @return array<string, mixed>
     */
    public function renew(string $csrPem): array
    {
        return $this->platform()->post('/agent/certificate/renew', ['csr_pem' => $csrPem]);
    }

    /**
     * @return array<string, mixed>
     */
    public function whoami(): array
    {
        return $this->platform()->get('/agent/whoami');
    }

    /**
     * Unauthenticated health probe used by the "test connection" button.
     *
     * @return array<string, mixed>
     */
    public function health(): array
    {
        $client = new HttpClient($this->config->apiBase(), $this->config->transportOptions(false));
        return $client->get('/agent/health');
    }
}
