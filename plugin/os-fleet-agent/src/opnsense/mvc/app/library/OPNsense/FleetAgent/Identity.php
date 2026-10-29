<?php

namespace OPNsense\FleetAgent;

use OPNsense\Core\Config;

/**
 * Device identity and X.509 material.
 *
 * The private key is generated locally, the CSR is sent to the platform and the
 * issued certificate is verified against the pinned CA before it replaces any
 * existing material. A failed enrollment therefore never leaves the firewall
 * without a usable identity.
 */
final class Identity
{
    private const OPENSSL_CONFIG = '/usr/local/openssl/openssl.cnf';

    /** @var array<string, mixed>|null */
    private ?array $productCache = null;

    public function hostname(): string
    {
        $hostname = trim((string)php_uname('n'));
        return $hostname !== '' ? $hostname : 'opnsense';
    }

    /**
     * Hardware serial number with deterministic fallbacks.
     *
     * dmidecode is preferred; OPNsense installations that do not ship it fall
     * back to the kernel host UUID so enrollment still has a stable identifier.
     */
    public function serialNumber(): string
    {
        foreach (['/usr/local/sbin/dmidecode', '/usr/sbin/dmidecode'] as $binary) {
            if (is_executable($binary)) {
                $result = Configd::capture($binary, ['-s', 'system-serial-number'], 5);
                $serial = $this->cleanIdentifier($result['ok'] ? $result['stdout'] : '');
                if ($serial !== '') {
                    return $serial;
                }
            }
        }

        $uuid = $this->sysctl('kern.hostuuid');
        if ($uuid !== null && $uuid !== '') {
            return 'uuid-' . $this->cleanIdentifier($uuid);
        }

        return 'host-' . substr(hash('sha256', $this->hostname() . php_uname('m')), 0, 24);
    }

    public function model(): string
    {
        $product = $this->productInfo();
        $name = trim((string)($product['product_name'] ?? ''));
        if ($name !== '') {
            return $name;
        }
        $hardware = $this->sysctl('hw.model');
        return $hardware !== null && $hardware !== '' ? $hardware : 'OPNsense';
    }

    public function firmwareVersion(): string
    {
        foreach (['/usr/local/opnsense/version/opnsense', '/usr/local/opnsense/version/core'] as $file) {
            $raw = Paths::read($file);
            if ($raw === null || trim($raw) === '') {
                continue;
            }
            $decoded = json_decode(trim($raw), true);
            if (is_array($decoded)) {
                foreach (['version', 'product_version', 'core'] as $key) {
                    if (!empty($decoded[$key]) && is_string($decoded[$key])) {
                        return $decoded[$key];
                    }
                }
            }
            $line = trim((string)strtok($raw, "\n"));
            if ($line !== '' && strlen($line) <= 64) {
                return $line;
            }
        }

        $product = $this->productInfo();
        if (!empty($product['product_version'])) {
            return (string)$product['product_version'];
        }

        $version = Configd::capture('/usr/local/sbin/opnsense-version', ['-v'], 10);
        if ($version['ok'] && trim($version['stdout']) !== '') {
            return trim((string)strtok($version['stdout'], "\n"));
        }

        return 'unknown';
    }

    public function macAddress(): ?string
    {
        $config = Config::getInstance()->object();
        foreach (['wan', 'lan'] as $interfaceName) {
            $device = isset($config->interfaces->{$interfaceName}->if)
                ? trim((string)$config->interfaces->{$interfaceName}->if)
                : '';
            if ($device !== '' && preg_match('/^[a-z0-9_.]+$/i', $device)) {
                $mac = $this->macFromInterface($device);
                if ($mac !== null) {
                    return $mac;
                }
            }
        }

        $list = Configd::capture('/sbin/ifconfig', ['-l'], 5);
        if ($list['ok']) {
            foreach (preg_split('/\s+/', trim($list['stdout'])) ?: [] as $device) {
                if ($device === '' || $device === 'lo0' || !preg_match('/^[a-z0-9_.]+$/i', $device)) {
                    continue;
                }
                $mac = $this->macFromInterface($device);
                if ($mac !== null) {
                    return $mac;
                }
            }
        }

        return null;
    }

    public function uptimeSeconds(): ?int
    {
        $boot = $this->sysctl('kern.boottime');
        if ($boot === null) {
            return null;
        }
        if (preg_match('/sec\s*=\s*(\d+)/', $boot, $matches)) {
            $seconds = time() - (int)$matches[1];
            return $seconds >= 0 ? $seconds : null;
        }
        return null;
    }

    /**
     * Free-form hardware profile submitted at enrollment.
     *
     * @return array<string, mixed>
     */
    public function hardwareProfile(): array
    {
        $memory = $this->sysctl('hw.physmem');
        $cores = $this->sysctl('hw.ncpu');
        $product = $this->productInfo();

        return [
            'cpu_model' => $this->sysctl('hw.model'),
            'cpu_cores' => $cores !== null && ctype_digit($cores) ? (int)$cores : null,
            'memory_bytes' => $memory !== null && ctype_digit($memory) ? (int)$memory : null,
            'disk_bytes' => (int)@disk_total_space('/'),
            'platform' => php_uname('s') . ' ' . php_uname('r'),
            'architecture' => php_uname('m'),
            'virtualization' => $this->sysctl('kern.vm_guest') ?? $this->sysctl('hw.hv_vmm_present'),
            'product_name' => $product['product_name'] ?? null,
            'product_version' => $product['product_version'] ?? null,
            'agent_version' => Paths::VERSION,
        ];
    }

    /**
     * Generate a new RSA private key and PKCS#10 CSR.
     *
     * @return array{key_pem: string, csr_pem: string}
     */
    public function generateKeyPair(string $commonName): array
    {
        $options = [
            'private_key_bits' => 2048,
            'private_key_type' => OPENSSL_KEYTYPE_RSA,
            'digest_alg' => 'sha256',
        ];
        if (is_file(self::OPENSSL_CONFIG)) {
            $options['config'] = self::OPENSSL_CONFIG;
        }

        $key = @openssl_pkey_new($options);
        if ($key === false) {
            throw new \RuntimeException('Unable to generate an RSA private key: ' . (string)openssl_error_string());
        }

        $keyPem = '';
        if (!@openssl_pkey_export($key, $keyPem, null, $options)) {
            throw new \RuntimeException('Unable to export the private key: ' . (string)openssl_error_string());
        }

        $csrPem = $this->createCsr($key, $commonName, $options);
        return ['key_pem' => $keyPem, 'csr_pem' => $csrPem];
    }

    /**
     * Create a CSR with the already installed private key.
     */
    public function csrForExistingKey(string $commonName): string
    {
        $keyPem = Paths::read(Paths::KEY_FILE);
        if ($keyPem === null || $keyPem === '') {
            throw new \RuntimeException('No private key is installed.');
        }
        $key = @openssl_pkey_get_private($keyPem);
        if ($key === false) {
            throw new \RuntimeException('The installed private key cannot be loaded.');
        }

        $options = ['digest_alg' => 'sha256'];
        if (is_file(self::OPENSSL_CONFIG)) {
            $options['config'] = self::OPENSSL_CONFIG;
        }
        return $this->createCsr($key, $commonName, $options);
    }

    /**
     * Validate and install a certificate and its CA.
     *
     * @return array{fingerprint: string, serial: string, valid_from: int, valid_to: int, days_left: int, subject_cn: string, issuer_cn: string}
     */
    public function installCertificate(string $certificatePem, string $caPem): array
    {
        $certificatePem = trim($certificatePem);
        $caPem = trim($caPem);
        if ($certificatePem === '' || $caPem === '') {
            throw new \InvalidArgumentException('The platform did not return a certificate and CA.');
        }

        $keyPem = Paths::read(Paths::KEY_FILE);
        if ($keyPem === null || $keyPem === '') {
            throw new \RuntimeException('The private key is missing; enroll again.');
        }
        $key = @openssl_pkey_get_private($keyPem);
        if ($key === false) {
            throw new \RuntimeException('The installed private key cannot be loaded.');
        }

        $certificate = @openssl_x509_read($certificatePem);
        if ($certificate === false) {
            throw new \InvalidArgumentException('The platform returned an invalid certificate.');
        }
        if (!@openssl_x509_check_private_key($certificate, $key)) {
            throw new \InvalidArgumentException('The issued certificate does not match the local private key.');
        }

        $caCertificate = @openssl_x509_read($caPem);
        if ($caCertificate === false) {
            throw new \InvalidArgumentException('The platform returned an invalid CA certificate.');
        }
        if (@openssl_x509_verify($certificate, $caPem) !== 1) {
            throw new \InvalidArgumentException('The issued certificate is not signed by the platform CA.');
        }

        $parsed = @openssl_x509_parse($certificatePem);
        if (!is_array($parsed)) {
            throw new \InvalidArgumentException('The issued certificate cannot be parsed.');
        }
        $validTo = (int)($parsed['validTo_time_t'] ?? 0);
        if ($validTo <= time()) {
            throw new \InvalidArgumentException('The issued certificate is already expired.');
        }

        $fingerprint = @openssl_x509_fingerprint($certificatePem, 'sha256');
        if ($fingerprint === false) {
            throw new \RuntimeException('Unable to compute the certificate fingerprint.');
        }

        Paths::write(Paths::CERT_FILE, $certificatePem . PHP_EOL, 0644);
        Paths::write(Paths::CA_FILE, $caPem . PHP_EOL, 0644);
        @chmod(Paths::KEY_FILE, 0600);

        $subject = is_array($parsed['subject'] ?? null) ? $parsed['subject'] : [];
        $issuer = is_array($parsed['issuer'] ?? null) ? $parsed['issuer'] : [];
        $daysLeft = (int)floor(($validTo - time()) / 86400);

        return [
            'fingerprint' => strtolower(str_replace([':', ' '], '', $fingerprint)),
            'serial' => (string)($parsed['serialNumber'] ?? ''),
            'valid_from' => (int)($parsed['validFrom_time_t'] ?? 0),
            'valid_to' => $validTo,
            'days_left' => max(0, $daysLeft),
            'subject_cn' => (string)($subject['CN'] ?? ''),
            'issuer_cn' => (string)($issuer['CN'] ?? ''),
        ];
    }

    public function writePrivateKey(string $pem): void
    {
        Paths::write(Paths::KEY_FILE, $pem . PHP_EOL, 0600);
    }

    /**
     * @return array<string, mixed>|null
     */
    public function certificateInfo(): ?array
    {
        $pem = Paths::read(Paths::CERT_FILE);
        if ($pem === null || $pem === '') {
            return null;
        }
        $parsed = @openssl_x509_parse($pem);
        if (!is_array($parsed)) {
            return null;
        }
        $fingerprint = @openssl_x509_fingerprint($pem, 'sha256');
        $validTo = (int)($parsed['validTo_time_t'] ?? 0);
        $subject = is_array($parsed['subject'] ?? null) ? $parsed['subject'] : [];
        $issuer = is_array($parsed['issuer'] ?? null) ? $parsed['issuer'] : [];

        return [
            'fingerprint' => $fingerprint !== false
                ? strtolower(str_replace([':', ' '], '', $fingerprint))
                : '',
            'serial' => (string)($parsed['serialNumber'] ?? ''),
            'valid_from' => (int)($parsed['validFrom_time_t'] ?? 0),
            'valid_from_iso' => gmdate('c', (int)($parsed['validFrom_time_t'] ?? 0)),
            'valid_to' => $validTo,
            'valid_to_iso' => gmdate('c', $validTo),
            'days_left' => (int)floor(($validTo - time()) / 86400),
            'subject_cn' => (string)($subject['CN'] ?? ''),
            'issuer_cn' => (string)($issuer['CN'] ?? ''),
            'expired' => $validTo <= time(),
        ];
    }

    public function fingerprint(): ?string
    {
        return Paths::fingerprintFromFile(Paths::CERT_FILE);
    }

    public function caFingerprint(): ?string
    {
        return Paths::fingerprintFromFile(Paths::CA_FILE);
    }

    public function renewalDue(int $days): bool
    {
        $info = $this->certificateInfo();
        if ($info === null) {
            return true;
        }
        return (int)$info['days_left'] <= $days;
    }

    public function commonName(): string
    {
        $base = 'device-' . $this->serialNumber();
        $sanitised = preg_replace('/[^A-Za-z0-9._-]+/', '-', $base) ?? '';
        $sanitised = trim($sanitised, '-');
        if ($sanitised === '') {
            $sanitised = 'device-' . substr(hash('sha256', $this->hostname()), 0, 16);
        }
        return substr($sanitised, 0, 64);
    }

    /**
     * @return array<string, mixed>
     */
    public function productInfo(): array
    {
        if ($this->productCache !== null) {
            return $this->productCache;
        }
        $decoded = Configd::json('firmware', 'product', [], 15);
        $this->productCache = is_array($decoded) ? $decoded : [];
        return $this->productCache;
    }

    private function createCsr($key, string $commonName, array $options): string
    {
        $distinguishedName = [
            'commonName' => $commonName,
            'organizationName' => 'OPNsense Fleet Manager',
            'organizationalUnitName' => 'Firewall',
            'countryName' => 'DE',
        ];
        $csr = @openssl_csr_new($distinguishedName, $key, $options);
        if ($csr === false) {
            throw new \RuntimeException('Unable to generate a CSR: ' . (string)openssl_error_string());
        }
        $csrPem = '';
        if (!@openssl_csr_export($csr, $csrPem)) {
            throw new \RuntimeException('Unable to export the CSR: ' . (string)openssl_error_string());
        }
        return $csrPem;
    }

    private function macFromInterface(string $device): ?string
    {
        $result = Configd::capture('/sbin/ifconfig', [$device], 5);
        if (!$result['ok']) {
            return null;
        }
        if (preg_match('/\bether\s+([0-9a-f]{2}(?::[0-9a-f]{2}){5})\b/i', $result['stdout'], $matches)) {
            return strtolower($matches[1]);
        }
        return null;
    }

    private function sysctl(string $name): ?string
    {
        $result = Configd::capture('/sbin/sysctl', ['-n', $name], 5);
        if (!$result['ok']) {
            return null;
        }
        $value = trim($result['stdout']);
        return $value !== '' ? $value : null;
    }

    private function cleanIdentifier(string $value): string
    {
        $value = trim($value);
        $value = preg_replace('/\s+/', '', $value) ?? '';
        $value = preg_replace('/[^A-Za-z0-9._:-]/', '', $value) ?? '';
        return substr($value, 0, 120);
    }
}
