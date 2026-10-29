<?php

namespace OPNsense\FleetAgent;

/**
 * Agent orchestration: enrollment, heartbeat, command execution,
 * configuration synchronisation, certificate renewal and the daemon loop.
 *
 * The daemon is deliberately single-threaded. Each cycle is short and
 * bounded, so a hung platform request can never block the firewall for longer
 * than the configured request timeout.
 */
final class Agent
{
    private AgentConfig $config;
    private Identity $identity;
    private Telemetry $telemetry;
    private AgentClient $client;
    private ConfigSync $configSync;
    private CommandRunner $commandRunner;

    /** @var resource|null */
    private $lockHandle = null;

    private bool $stopping = false;
    private int $cycles = 0;

    public function __construct(?AgentConfig $config = null)
    {
        $this->config = $config ?? new AgentConfig();
        $this->identity = new Identity();
        $this->telemetry = new Telemetry($this->config, $this->identity);
        $this->client = new AgentClient($this->config, $this->identity);
        $this->configSync = new ConfigSync($this->config, $this->client);
        $this->commandRunner = new CommandRunner(
            $this->config,
            $this->configSync,
            fn(): array => $this->renew(),
            fn(): array => $this->diagnostics()
        );

        Logger::setLevel($this->config->logLevel());
        Paths::ensure();
    }

    public function config(): AgentConfig
    {
        return $this->config;
    }

    public function configSync(): ConfigSync
    {
        return $this->configSync;
    }

    /**
     * Execute a single command locally. Used by the CLI and by tests.
     *
     * @param array<string, mixed> $payload
     * @return array<string, mixed>
     */
    public function executeCommand(string $action, array $payload = []): array
    {
        return $this->commandRunner->execute([
            'id' => 'cli-' . bin2hex(random_bytes(8)),
            'action' => $action,
            'payload' => $payload,
        ]);
    }

    /**
     * Run a single agent cycle.
     *
     * @return array<string, mixed>
     */
    public function runCycle(bool $force = false): array
    {
        $started = microtime(true);
        $result = [
            'started_at' => gmdate('c'),
            'status' => 'ok',
            'enrollment' => null,
            'renewal' => null,
            'heartbeat' => null,
            'commands' => null,
            'config' => null,
            'errors' => [],
        ];

        if (!$this->config->enabled()) {
            $result['status'] = 'disabled';
            $result['finished_at'] = gmdate('c');
            return $result;
        }

        if (!Paths::isEnrolled()) {
            if ($this->config->enrollmentToken() === '') {
                $result['status'] = 'unenrolled';
                $result['finished_at'] = gmdate('c');
                return $result;
            }
            try {
                $result['enrollment'] = (new Enrollment($this->config))->enroll($this->config->enrollmentToken());
            } catch (\Throwable $exception) {
                $this->recordError($exception, 'Enrollment failed');
                $result['status'] = 'error';
                $result['errors'][] = 'enrollment: ' . $exception->getMessage();
                $result['finished_at'] = gmdate('c');
                return $result;
            }
        }

        if ($this->identity->renewalDue($this->config->renewBeforeDays())) {
            try {
                $result['renewal'] = $this->renew();
            } catch (\Throwable $exception) {
                $this->recordError($exception, 'Certificate renewal failed');
                $result['errors'][] = 'renewal: ' . $exception->getMessage();
            }
        }

        $now = time();
        $forceHeartbeat = $force || (bool)State::get('force_heartbeat', false);
        $heartbeatDue = $this->heartbeatDue($now);

        if ($forceHeartbeat || $heartbeatDue) {
            if ($forceHeartbeat) {
                State::set('force_heartbeat', false);
            }
            State::set('last_heartbeat_attempt_epoch', $now);
            try {
                $result['heartbeat'] = $this->heartbeat();
            } catch (\Throwable $exception) {
                $this->recordError($exception, 'Heartbeat failed');
                $result['errors'][] = 'heartbeat: ' . $exception->getMessage();
            }

            try {
                $result['commands'] = $this->pollCommands();
            } catch (\Throwable $exception) {
                $this->recordError($exception, 'Command polling failed');
                $result['errors'][] = 'commands: ' . $exception->getMessage();
            }
        }

        $configDue = $force || $now - (int)State::get('last_config_attempt_epoch', 0) >= $this->config->configInterval();
        if ($configDue) {
            State::set('last_config_attempt_epoch', $now);
            try {
                $result['config'] = $this->configSync->sync($force);
                if (($result['config']['errors'] ?? []) !== []) {
                    foreach ($result['config']['errors'] as $error) {
                        $result['errors'][] = 'config: ' . $error;
                    }
                }
            } catch (\Throwable $exception) {
                $this->recordError($exception, 'Configuration synchronisation failed');
                $result['errors'][] = 'config: ' . $exception->getMessage();
            }
        }

        if ($result['errors'] !== []) {
            $result['status'] = 'error';
        }

        $result['finished_at'] = gmdate('c');
        $result['duration_ms'] = (int)round((microtime(true) - $started) * 1000);
        $this->cycles++;

        return $result;
    }

    /**
     * @return array<string, mixed>
     */
    public function heartbeat(): array
    {
        $payload = $this->telemetry->collect();
        $pending = State::get('command_results', []);
        $pending = is_array($pending) ? array_slice($pending, -25) : [];
        if ($pending !== []) {
            $payload['command_results'] = $pending;
        }

        $response = $this->client->heartbeat($payload);
        if (
            !in_array($response['status'], [200, 201], true)
            || !is_array($response['json'])
            || empty($response['json']['accepted'])
        ) {
            throw new \RuntimeException(
                'The platform rejected the heartbeat: ' . $this->describe($response)
            );
        }

        if ($pending !== []) {
            $this->clearReportedResults($pending);
        }

        $now = gmdate('c');
        $this->config->recordHeartbeat($now);
        State::merge([
            'last_heartbeat_epoch' => time(),
            'last_heartbeat_at' => $now,
            'consecutive_failures' => 0,
            'last_error' => null,
            'last_error_at' => null,
        ]);
        $this->clearConfigError();

        return $response['json'];
    }

    /**
     * Pull pending commands, execute them and persist their results until the
     * next heartbeat has been accepted by the platform.
     *
     * @return array<string, mixed>
     */
    public function pollCommands(): array
    {
        $response = $this->client->commands();
        if ($response['status'] !== 200 || !is_array($response['json'])) {
            throw new \RuntimeException('Unable to poll commands: ' . $this->describe($response));
        }

        $commands = is_array($response['json']['commands'] ?? null) ? $response['json']['commands'] : [];
        $results = [];
        foreach ($commands as $command) {
            if (is_array($command)) {
                $results[] = $this->commandRunner->execute($command);
            }
        }

        if ($results !== []) {
            State::appendCommandResults($results);
            State::set('last_command_poll_at', gmdate('c'));
        }

        return [
            'received' => count($commands),
            'executed' => count($results),
            'results' => array_map(
                static fn(array $result): array => [
                    'id' => $result['id'] ?? '',
                    'action' => $result['action'] ?? '',
                    'status' => $result['status'] ?? '',
                ],
                $results
            ),
        ];
    }

    /**
     * Renew the device certificate using the installed private key.
     *
     * @return array<string, mixed>
     */
    public function renew(): array
    {
        if (!Paths::isEnrolled()) {
            throw new \RuntimeException('The device is not enrolled.');
        }

        $csr = $this->identity->csrForExistingKey($this->identity->commonName());
        $response = $this->client->renew($csr);
        if (!in_array($response['status'], [200, 201], true) || !is_array($response['json'])) {
            throw new \RuntimeException('Certificate renewal failed: ' . $this->describe($response));
        }

        $data = $response['json'];
        foreach (['serial_number', 'certificate_pem', 'ca_pem'] as $field) {
            if (empty($data[$field]) || !is_string($data[$field])) {
                throw new \RuntimeException(sprintf('The renewal response is missing %s.', $field));
            }
        }

        $certificate = $this->identity->installCertificate($data['certificate_pem'], $data['ca_pem']);

        $model = $this->config->model();
        $model->certificate_serial = (string)$data['serial_number'];
        $fingerprint = $this->identity->caFingerprint();
        if ($fingerprint !== null) {
            $model->ca_fingerprint = $fingerprint;
        }
        $this->config->save();

        State::merge([
            'last_renewal_at' => gmdate('c'),
            'certificate_serial' => (string)$data['serial_number'],
            'certificate_valid_to' => gmdate('c', (int)$certificate['valid_to']),
            'certificate_days_left' => $certificate['days_left'] ?? null,
        ]);

        Logger::info('Device certificate renewed', [
            'serial_number' => (string)$data['serial_number'],
            'days_left' => $certificate['days_left'],
            'fingerprint' => $certificate['fingerprint'],
        ]);

        return [
            'serial_number' => (string)$data['serial_number'],
            'valid_to' => gmdate('c', (int)$certificate['valid_to']),
            'days_left' => $certificate['days_left'],
            'certificate' => $certificate,
        ];
    }

    /**
     * Enroll explicitly, for example from the UI or CLI.
     *
     * @return array<string, mixed>
     */
    public function enroll(): array
    {
        $token = $this->config->enrollmentToken();
        if ($token === '') {
            throw new \RuntimeException('No enrollment token is configured.');
        }
        return (new Enrollment($this->config))->enroll($token);
    }

    /**
     * Non-secret status document used by the API and the CLI.
     *
     * @return array<string, mixed>
     */
    public function status(): array
    {
        $certificate = null;
        try {
            $certificate = $this->identity->certificateInfo();
        } catch (\Throwable $exception) {
            Logger::debug('Unable to read certificate status', ['error' => $exception->getMessage()]);
        }

        $state = State::all();

        return [
            'agent_version' => Paths::VERSION,
            'enabled' => $this->config->enabled(),
            'enrolled' => Paths::isEnrolled(),
            'service_running' => Paths::serviceRunning(),
            'pid' => $this->readPid(),
            'device_id' => $this->config->deviceId(),
            'device_name' => $this->config->deviceName(),
            'platform_url' => $this->config->platformUrl(),
            'api_base' => $this->config->apiBase(),
            'heartbeat_url' => $this->config->heartbeatUrl(),
            'heartbeat_interval' => $this->config->heartbeatInterval(),
            'config_interval' => $this->config->configInterval(),
            'apply_aliases' => $this->config->applyAliases(),
            'apply_firewall_rules' => $this->config->applyFirewallRules(),
            'certificate' => $certificate,
            'last_seen' => $state['last_heartbeat_at'] ?? $this->config->lastSeen(),
            'last_config_hash' => $state['last_config_hash'] ?? $this->config->lastConfigHash(),
            'last_desired_hash' => $state['desired_hash'] ?? null,
            'last_apply' => $state['last_apply_report'] ?? null,
            'last_error' => $state['last_error'] ?? null,
            'last_error_at' => $state['last_error_at'] ?? null,
            'consecutive_failures' => (int)($state['consecutive_failures'] ?? 0),
            'pending_command_results' => is_array($state['command_results'] ?? null)
                ? count($state['command_results'])
                : 0,
            'log_level' => Logger::level(),
            'timestamp' => gmdate('c'),
        ];
    }

    /**
     * Collect a diagnostics bundle and persist it under the configuration
     * directory. The bundle intentionally excludes the private key, the
     * enrollment token and any other secret.
     *
     * @return array<string, mixed>
     */
    public function diagnostics(): array
    {
        $payload = [
            'generated_at' => gmdate('c'),
            'status' => $this->status(),
            'settings' => $this->config->export(),
            'telemetry' => $this->telemetry->collect(),
            'system' => [
                'hostname' => $this->identity->hostname(),
                'serial_number' => $this->identity->serialNumber(),
                'model' => $this->identity->model(),
                'firmware_version' => $this->identity->firmwareVersion(),
                'php_version' => PHP_VERSION,
                'openssl_version' => defined('OPENSSL_VERSION_TEXT') ? OPENSSL_VERSION_TEXT : null,
                'uname' => php_uname(),
                'disk_total_bytes' => (int)@disk_total_space('/'),
                'disk_free_bytes' => (int)@disk_free_space('/'),
            ],
            'files' => [
                'certificate' => is_file(Paths::CERT_FILE),
                'private_key' => is_file(Paths::KEY_FILE),
                'ca' => is_file(Paths::CA_FILE),
                'managed_objects' => is_file(Paths::MANAGED_FILE),
            ],
            'apply_report' => $this->readJson(Paths::APPLY_FILE),
            'log' => Logger::tail(200),
        ];

        Paths::ensure();
        $filename = sprintf('diagnostics-%s.json', gmdate('Ymd\THis\Z'));
        $path = Paths::DIAGNOSTICS_DIR . '/' . $filename;
        $encoded = json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
        if ($encoded === false) {
            throw new \RuntimeException('Unable to encode the diagnostics bundle.');
        }
        Paths::write($path, $encoded . PHP_EOL, 0600);
        $this->pruneDiagnostics();

        return [
            'path' => $path,
            'generated_at' => $payload['generated_at'],
            'payload' => $payload,
        ];
    }

    /**
     * Remove enrollment material and transient state.
     *
     * @return array<string, mixed>
     */
    public function reset(): array
    {
        $model = $this->config->model();
        $model->device_id = '';
        $model->device_name = '';
        $model->certificate_serial = '';
        $model->ca_fingerprint = '';
        $model->heartbeat_url = '';
        $model->enrollment_token = '';
        $model->last_seen = '';
        $model->last_config_hash = '';
        $model->last_error = '';
        $this->config->save();

        Paths::reset();
        State::clear();

        Logger::warning('OFME Fleet Agent enrolment was reset');

        return [
            'status' => 'reset',
            'enrolled' => false,
            'reset_at' => gmdate('c'),
        ];
    }

    /**
     * Check whether the platform is reachable and response.
     *
     * @return array<string, mixed>
     */
    public function testConnection(): array
    {
        $response = $this->client->health();
        if ($response['status'] !== 200 || !is_array($response['json'])) {
            throw new \RuntimeException('Platform unreachable: ' . $this->describe($response));
        }
        return [
            'status' => 'ok',
            'message' => 'Platform reachable.',
            'platform' => $response['json'],
        ];
    }

    /**
     * Run the blocking daemon loop.
     */
    public function runDaemon(int $maxCycles = 0): void
    {
        $this->acquireLock();
        $this->writePid();
        $this->installSignalHandlers();

        Logger::info('OFME Fleet Agent daemon started', [
            'version' => Paths::VERSION,
            'pid' => getmypid(),
            'max_cycles' => $maxCycles,
        ]);

        try {
            while (!$this->stopping) {
                $cycle = $this->runCycle(false);
                if ($cycle['status'] === 'error') {
                    Logger::warning('Agent cycle completed with errors', [
                        'errors' => $cycle['errors'],
                        'duration_ms' => $cycle['duration_ms'],
                    ]);
                }

                if ($maxCycles > 0 && $this->cycles >= $maxCycles) {
                    break;
                }

                if ((bool)State::get('restart_requested', false)) {
                    State::set('restart_requested', false);
                    Logger::info('Restart requested by a platform command');
                    $this->restartService();
                    break;
                }

                $sleep = $this->nextSleepSeconds();
                for ($i = 0; $i < $sleep && !$this->stopping; $i++) {
                    if ((bool)State::get('restart_requested', false)) {
                        break;
                    }
                    sleep(1);
                }
            }
        } finally {
            Logger::info('OFME Fleet Agent daemon stopped', ['pid' => getmypid()]);
            $this->releaseLock();
            $this->removePid();
        }
    }

    public function stop(): void
    {
        $this->stopping = true;
    }

    private function installSignalHandlers(): void
    {
        if (!function_exists('pcntl_signal') || !function_exists('pcntl_async_signals')) {
            return;
        }
        pcntl_async_signals(true);
        $handler = function (): void {
            $this->stopping = true;
        };
        pcntl_signal(SIGTERM, $handler);
        pcntl_signal(SIGINT, $handler);
        pcntl_signal(SIGHUP, function (): void {
            Logger::setLevel($this->config->logLevel());
            Logger::info('Configuration reloaded after SIGHUP');
        });
    }

    private function acquireLock(): void
    {
        $handle = @fopen(Paths::LOCK_FILE, 'c');
        if ($handle === false) {
            throw new \RuntimeException('Unable to open the agent lock file.');
        }
        if (!flock($handle, LOCK_EX | LOCK_NB)) {
            fclose($handle);
            throw new \RuntimeException('Another agent instance is already running.');
        }
        $this->lockHandle = $handle;
    }

    private function releaseLock(): void
    {
        if (is_resource($this->lockHandle)) {
            flock($this->lockHandle, LOCK_UN);
            fclose($this->lockHandle);
            $this->lockHandle = null;
        }
    }

    private function writePid(): void
    {
        if (is_file(Paths::PID_FILE)) {
            $existing = trim((string)Paths::read(Paths::PID_FILE));
            if ($existing !== '' && ctype_digit($existing) && (int)$existing !== getmypid() && @posix_kill((int)$existing, 0)) {
                throw new \RuntimeException('Another agent instance is already running.');
            }
        }
        Paths::write(Paths::PID_FILE, (string)getmypid(), 0644);
    }

    private function removePid(): void
    {
        $existing = trim((string)Paths::read(Paths::PID_FILE));
        if ($existing !== '' && (int)$existing === getmypid()) {
            Paths::delete(Paths::PID_FILE);
        }
    }

    private function readPid(): ?int
    {
        $pid = trim((string)Paths::read(Paths::PID_FILE));
        return $pid !== '' && ctype_digit($pid) ? (int)$pid : null;
    }

    private function heartbeatDue(int $now): bool
    {
        $last = (int)State::get('last_heartbeat_attempt_epoch', 0);
        if ($last === 0) {
            return true;
        }
        return $now - $last >= $this->heartbeatIntervalWithBackoff();
    }

    private function heartbeatIntervalWithBackoff(): int
    {
        $base = $this->config->heartbeatInterval();
        $failures = max(0, (int)State::get('consecutive_failures', 0));
        if ($failures === 0) {
            return $base;
        }
        $factor = 2 ** min($failures, 4);
        return (int)min(900, $base * $factor);
    }

    private function nextSleepSeconds(): int
    {
        if ((bool)State::get('force_heartbeat', false) || (bool)State::get('restart_requested', false)) {
            return 1;
        }

        $now = time();
        $nextHeartbeat = (int)State::get('last_heartbeat_attempt_epoch', 0) + $this->heartbeatIntervalWithBackoff();
        $nextConfig = (int)State::get('last_config_attempt_epoch', 0) + $this->config->configInterval();
        $next = min($nextHeartbeat, $nextConfig) - $now;
        return max(1, min(30, $next));
    }

    /**
     * @param list<array<string, mixed>> $reported
     */
    private function clearReportedResults(array $reported): void
    {
        $pending = State::get('command_results', []);
        if (!is_array($pending)) {
            State::set('command_results', []);
            return;
        }

        $ids = [];
        foreach ($reported as $result) {
            $identifier = (string)($result['id'] ?? '');
            if ($identifier !== '') {
                $ids[$identifier] = true;
            }
        }

        if ($ids === []) {
            $remaining = array_slice($pending, count($reported));
        } else {
            $remaining = [];
            foreach ($pending as $result) {
                $identifier = (string)($result['id'] ?? '');
                if ($identifier !== '' && isset($ids[$identifier])) {
                    continue;
                }
                $remaining[] = $result;
            }
        }

        State::set('command_results', array_values($remaining));
    }

    private function recordError(\Throwable $exception, string $context): void
    {
        $message = $context . ': ' . $exception->getMessage();
        $previous = (string)State::get('last_error', '');
        $failures = (int)State::get('consecutive_failures', 0) + 1;
        State::merge([
            'last_error' => $message,
            'last_error_at' => gmdate('c'),
            'consecutive_failures' => $failures,
        ]);
        Logger::exception($exception, $context);

        if ($message === $previous) {
            return;
        }
        try {
            $model = $this->config->model();
            $model->last_error = substr($message, 0, 1024);
            $this->config->save();
        } catch (\Throwable $saveException) {
            Logger::warning('Unable to persist the last error', [
                'error' => $saveException->getMessage(),
            ]);
        }
    }

    private function clearConfigError(): void
    {
        $model = $this->config->model();
        if ((string)$model->last_error === '') {
            return;
        }
        try {
            $model->last_error = '';
            $this->config->save();
        } catch (\Throwable $exception) {
            Logger::debug('Unable to clear the persisted agent error', [
                'error' => $exception->getMessage(),
            ]);
        }
    }

    private function restartService(): void
    {
        $daemon = is_executable('/usr/local/sbin/daemon')
            ? '/usr/local/sbin/daemon'
            : '/usr/sbin/daemon';
        $result = Configd::capture($daemon, [Paths::RC_SCRIPT, 'onerestart'], 10);
        if (!$result['ok']) {
            Logger::warning('Unable to schedule the agent restart', [
                'exit_code' => $result['code'],
                'stderr' => $result['stderr'],
            ]);
        }
    }

    private function pruneDiagnostics(): void
    {
        $files = glob(Paths::DIAGNOSTICS_DIR . '/diagnostics-*.json') ?: [];
        sort($files);
        while (count($files) > 20) {
            $file = array_shift($files);
            if ($file !== null) {
                Paths::delete($file);
            }
        }
    }

    /**
     * @return array<string, mixed>|null
     */
    private function readJson(string $path): ?array
    {
        $raw = Paths::read($path);
        if ($raw === null || trim($raw) === '') {
            return null;
        }
        $decoded = json_decode($raw, true);
        return is_array($decoded) ? $decoded : null;
    }

    /**
     * @param array<string, mixed> $response
     */
    private function describe(array $response): string
    {
        return (new Enrollment($this->config))->describe($response);
    }
}
