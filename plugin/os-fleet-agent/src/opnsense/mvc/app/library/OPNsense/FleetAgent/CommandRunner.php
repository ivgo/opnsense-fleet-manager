<?php

namespace OPNsense\FleetAgent;

/**
 * Executes the small, fixed command set accepted from the platform.
 *
 * There is deliberately no generic shell action. Every supported action maps
 * to a fixed operation, and unknown actions are refused and reported as
 * ignored. Results are bounded before they are persisted in state.json.
 */
final class CommandRunner
{
    public const ACTIONS = [
        'noop',
        'ping',
        'sync_config',
        'renew_certificate',
        'restart_agent',
        'collect_diagnostics',
        'reload_firewall',
        'update_telemetry',
    ];

    private const MAX_MESSAGE = 512;

    /** @var callable */
    private $renew;

    /** @var callable */
    private $diagnostics;

    public function __construct(
        private AgentConfig $config,
        private ConfigSync $configSync,
        callable $renew,
        callable $diagnostics
    ) {
        $this->renew = $renew;
        $this->diagnostics = $diagnostics;
    }

    /**
     * @param array<string, mixed> $command
     * @return array<string, mixed>
     */
    public function execute(array $command): array
    {
        $identifier = (string)($command['id'] ?? $command['command_id'] ?? '');
        $action = strtolower(trim((string)($command['action'] ?? $command['command'] ?? '')));
        $payload = is_array($command['payload'] ?? null) ? $command['payload'] : [];

        $started = microtime(true);
        $result = [
            'id' => $identifier,
            'action' => $action,
            'status' => 'error',
            'message' => '',
            'output' => null,
            'started_at' => gmdate('c'),
            'finished_at' => null,
            'duration_ms' => 0,
        ];

        try {
            if (!in_array($action, self::ACTIONS, true)) {
                $result['status'] = 'ignored';
                $result['message'] = 'Action is not in the agent command whitelist.';
            } else {
                $result = array_merge($result, $this->run($action, $payload));
            }
        } catch (\Throwable $exception) {
            $result['status'] = 'error';
            $result['message'] = $this->truncate($exception->getMessage());
            Logger::exception($exception, 'Command failed');
        }

        $result['message'] = $this->truncate((string)$result['message']);
        $result['finished_at'] = gmdate('c');
        $result['duration_ms'] = (int)round((microtime(true) - $started) * 1000);

        Logger::info('Command executed', [
            'id' => $identifier,
            'action' => $action,
            'status' => $result['status'],
            'duration_ms' => $result['duration_ms'],
        ]);

        return $result;
    }

    /**
     * @param array<string, mixed> $payload
     * @return array<string, mixed>
     */
    private function run(string $action, array $payload): array
    {
        switch ($action) {
            case 'noop':
                return ['status' => 'ok', 'message' => 'No operation performed.', 'output' => ['noop' => true]];

            case 'ping':
                $identity = new Identity();
                return [
                    'status' => 'ok',
                    'message' => 'pong',
                    'output' => [
                        'pong' => true,
                        'agent_version' => Paths::VERSION,
                        'hostname' => $identity->hostname(),
                        'uptime_seconds' => $identity->uptimeSeconds(),
                        'server_time' => gmdate('c'),
                    ],
                ];

            case 'sync_config':
                $report = $this->configSync->sync(true);
                return [
                    'status' => ($report['errors'] ?? []) === [] ? 'ok' : 'error',
                    'message' => ($report['errors'] ?? []) === []
                        ? 'Desired configuration synchronised.'
                        : implode('; ', array_map('strval', $report['errors'])),
                    'output' => [
                        'status' => $report['status'] ?? null,
                        'config_hash' => $report['config_hash'] ?? null,
                        'aliases' => $this->counts($report['aliases'] ?? []),
                        'firewall_rules' => $this->counts($report['firewall_rules'] ?? []),
                        'errors' => array_slice((array)($report['errors'] ?? []), 0, 5),
                    ],
                ];

            case 'renew_certificate':
                $renewed = call_user_func($this->renew);
                return [
                    'status' => 'ok',
                    'message' => 'Certificate renewed.',
                    'output' => [
                        'serial_number' => $renewed['serial_number'] ?? null,
                        'valid_to' => $renewed['valid_to'] ?? null,
                        'days_left' => $renewed['days_left'] ?? null,
                    ],
                ];

            case 'restart_agent':
                State::set('restart_requested', true);
                return [
                    'status' => 'ok',
                    'message' => 'Agent restart scheduled after the command result is reported.',
                    'output' => ['scheduled' => true],
                ];

            case 'collect_diagnostics':
                $diagnostics = call_user_func($this->diagnostics);
                return [
                    'status' => 'ok',
                    'message' => 'Diagnostics collected.',
                    'output' => [
                        'path' => $diagnostics['path'] ?? null,
                        'generated_at' => $diagnostics['generated_at'] ?? null,
                    ],
                ];

            case 'reload_firewall':
                $reload = Configd::run('filter', 'reload', [], 90);
                return [
                    'status' => $reload['ok'] ? 'ok' : 'error',
                    'message' => $reload['ok']
                        ? 'Filter reloaded.'
                        : ($reload['stderr'] !== '' ? $reload['stderr'] : 'Filter reload failed.'),
                    'output' => [
                        'ok' => $reload['ok'],
                        'exit_code' => $reload['code'],
                        'timed_out' => $reload['timed_out'],
                    ],
                ];

            case 'update_telemetry':
                State::set('force_heartbeat', true);
                return [
                    'status' => 'ok',
                    'message' => 'A heartbeat will be sent on the next cycle.',
                    'output' => ['scheduled' => true],
                ];
        }

        return ['status' => 'ignored', 'message' => 'Unsupported action.'];
    }

    /**
     * @param mixed $plan
     * @return array<string, int>
     */
    private function counts($plan): array
    {
        if (!is_array($plan)) {
            return [];
        }
        $counts = [];
        foreach (['create', 'update', 'delete', 'unchanged', 'conflicts'] as $key) {
            if (isset($plan[$key]) && is_array($plan[$key])) {
                $counts[$key] = count($plan[$key]);
            }
        }
        return $counts;
    }

    private function truncate(string $message): string
    {
        $message = trim(preg_replace('/\s+/u', ' ', $message) ?? $message);
        return strlen($message) <= self::MAX_MESSAGE
            ? $message
            : substr($message, 0, self::MAX_MESSAGE) . '...';
    }
}
