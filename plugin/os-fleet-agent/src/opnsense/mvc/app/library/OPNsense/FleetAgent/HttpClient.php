<?php

namespace OPNsense\FleetAgent;

/**
 * JSON-over-HTTPS client with optional mutual TLS.
 *
 * The client never follows redirects: the platform API is a fixed origin and
 * following a redirect could leak the device certificate to another host.
 */
final class HttpClient
{
    private string $baseUrl;

    /** @var array<string, mixed> */
    private array $options;

    public function __construct(string $baseUrl, array $options = [])
    {
        $this->baseUrl = rtrim($baseUrl, '/');
        $this->options = array_merge(
            [
                'verify' => true,
                'ca_file' => null,
                'cert_file' => null,
                'key_file' => null,
                'proxy' => '',
                'timeout' => 20,
                'retries' => 2,
                'user_agent' => 'os-fleet-agent/' . Paths::VERSION,
                'headers' => [],
            ],
            $options
        );
    }

    public function baseUrl(): string
    {
        return $this->baseUrl;
    }

    /**
     * @param array<string, scalar|null> $query
     * @param list<string> $headers
     * @return array<string, mixed>
     */
    public function get(string $path, array $query = [], array $headers = []): array
    {
        return $this->request('GET', $path, null, $headers, $query);
    }

    /**
     * @param array<string, mixed>|string|null $body
     * @param list<string> $headers
     * @return array<string, mixed>
     */
    public function post(string $path, $body = null, array $headers = []): array
    {
        return $this->request('POST', $path, $body, $headers);
    }

    /**
     * @param array<string, mixed>|string|null $body
     * @param list<string> $headers
     * @param array<string, scalar|null> $query
     * @return array<string, mixed>
     */
    public function request(
        string $method,
        string $path,
        $body = null,
        array $headers = [],
        array $query = []
    ): array {
        if (!extension_loaded('curl')) {
            throw new \RuntimeException('The PHP cURL extension is required by os-fleet-agent.');
        }

        $url = $this->buildUrl($path, $query);
        $payload = null;
        if ($body !== null) {
            $payload = is_string($body)
                ? $body
                : json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
            if ($payload === false) {
                throw new \InvalidArgumentException('Unable to encode the request body as JSON.');
            }
        }

        $requestHeaders = array_merge(
            [
                'Accept: application/json',
                'Content-Type: application/json',
                'Expect:',
                'User-Agent: ' . (string)$this->options['user_agent'],
            ],
            array_values((array)$this->options['headers']),
            $headers
        );

        $attempts = max(0, (int)$this->options['retries']);
        $last = null;
        for ($attempt = 0; $attempt <= $attempts; $attempt++) {
            $last = $this->execute($method, $url, $payload, $requestHeaders);
            $status = (int)$last['status'];
            $retryable = $last['error'] !== null || in_array($status, [429, 500, 502, 503, 504], true);
            if (!$retryable || $attempt === $attempts) {
                return $last;
            }
            usleep((int)(250000 * (2 ** $attempt)));
        }

        return $last ?? [
            'status' => 0,
            'json' => null,
            'body' => '',
            'headers' => [],
            'error' => 'request failed',
            'duration_ms' => 0,
        ];
    }

    /**
     * @param list<string> $headers
     * @return array<string, mixed>
     */
    private function execute(string $method, string $url, ?string $payload, array $headers): array
    {
        $handle = curl_init();
        if ($handle === false) {
            throw new \RuntimeException('Unable to initialise cURL.');
        }

        $responseHeaders = [];
        $responseBody = '';
        $started = microtime(true);
        $verify = (bool)$this->options['verify'];

        $curlOptions = [
            CURLOPT_URL => $url,
            CURLOPT_RETURNTRANSFER => false,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_CONNECTTIMEOUT => min(10, max(1, (int)$this->options['timeout'])),
            CURLOPT_TIMEOUT => max(1, (int)$this->options['timeout']),
            CURLOPT_SSL_VERIFYPEER => $verify,
            CURLOPT_SSL_VERIFYHOST => $verify ? 2 : 0,
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_CUSTOMREQUEST => strtoupper($method),
            CURLOPT_WRITEFUNCTION => function ($curl, string $chunk) use (&$responseBody): int {
                $responseBody .= $chunk;
                return strlen($chunk);
            },
            CURLOPT_HEADERFUNCTION => function ($curl, string $line) use (&$responseHeaders): int {
                $trimmed = trim($line);
                if ($trimmed === '' || strpos($trimmed, ':') === false) {
                    return strlen($line);
                }
                [$name, $value] = explode(':', $trimmed, 2);
                $responseHeaders[strtolower(trim($name))] = trim($value);
                return strlen($line);
            },
        ];

        if ($this->options['ca_file'] !== null) {
            $curlOptions[CURLOPT_CAINFO] = (string)$this->options['ca_file'];
        }
        if ($this->options['cert_file'] !== null && $this->options['key_file'] !== null) {
            $curlOptions[CURLOPT_SSLCERT] = (string)$this->options['cert_file'];
            $curlOptions[CURLOPT_SSLKEY] = (string)$this->options['key_file'];
            $curlOptions[CURLOPT_SSLCERTTYPE] = 'PEM';
            $curlOptions[CURLOPT_SSLKEYTYPE] = 'PEM';
        }
        if ((string)$this->options['proxy'] !== '') {
            $curlOptions[CURLOPT_PROXY] = (string)$this->options['proxy'];
        }
        if ($payload !== null) {
            $curlOptions[CURLOPT_POSTFIELDS] = $payload;
        }

        curl_setopt_array($handle, $curlOptions);
        $ok = curl_exec($handle);
        $errno = curl_errno($handle);
        $error = $errno !== 0 ? curl_error($handle) : null;
        $status = (int)curl_getinfo($handle, CURLINFO_RESPONSE_CODE);
        curl_close($handle);

        $decoded = null;
        if ($responseBody !== '') {
            $json = json_decode($responseBody, true);
            if (is_array($json)) {
                $decoded = $json;
            }
        }

        if ($ok === false && $error === null) {
            $error = 'request failed';
        }

        return [
            'status' => $status,
            'json' => $decoded,
            'body' => $responseBody,
            'headers' => $responseHeaders,
            'error' => $error,
            'duration_ms' => (int)round((microtime(true) - $started) * 1000),
        ];
    }

    /**
     * @param array<string, scalar|null> $query
     */
    private function buildUrl(string $path, array $query): string
    {
        if (preg_match('~^https?://~i', $path)) {
            $url = $path;
        } else {
            $url = $this->baseUrl . '/' . ltrim($path, '/');
        }

        if ($query !== []) {
            $separator = strpos($url, '?') === false ? '?' : '&';
            $url .= $separator . http_build_query($query, '', '&', PHP_QUERY_RFC3986);
        }
        return $url;
    }
}
