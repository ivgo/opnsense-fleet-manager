<?php

namespace OPNsense\FleetAgent\Api;

use OPNsense\Base\ApiControllerBase;
use OPNsense\Core\Backend;
use OPNsense\Core\Config;
use OPNsense\FleetAgent\CommandRunner;
use OPNsense\FleetAgent\Settings;

/**
 * Operational API for the OFME Fleet Agent.
 *
 * All long-running or privileged actions are delegated to configd actions in
 * actions_ofme.conf. This controller only validates the requested operation and
 * decodes the JSON document produced by the agent CLI.
 */
class AgentController extends ApiControllerBase
{
    private const SERVICE_COMMANDS = ['start', 'stop', 'restart', 'status'];

    public function statusAction()
    {
        return $this->runAgent('ofme agent.status', 30);
    }

    public function enrollAction()
    {
        if (!$this->request->isPost()) {
            return $this->methodError();
        }

        $token = trim((string)$this->request->getPost('token', null, ''));
        if ($token !== '') {
            if (strlen($token) < 16 || strlen($token) > 512) {
                return [
                    'status' => 'error',
                    'message' => 'The enrollment token must be between 16 and 512 characters.',
                ];
            }
            try {
                $model = new Settings();
                $model->enrollment_token = $token;
                $model->serializeToConfig();
                Config::getInstance()->save();
            } catch (\Throwable $exception) {
                return ['status' => 'error', 'message' => $exception->getMessage()];
            }
        }

        $result = $this->runAgent('ofme agent.enroll', 180);
        if (($result['status'] ?? '') === 'enrolled') {
            $settings = new Settings();
            if ((string)$settings->enabled === '1') {
                try {
                    (new Backend())->configdRun('ofme restart', true);
                } catch (\Throwable $exception) {
                    $result['service_warning'] = $exception->getMessage();
                }
            }
        }

        return $result;
    }

    public function renewAction()
    {
        if (!$this->request->isPost()) {
            return $this->methodError();
        }
        return $this->runAgent('ofme agent.renew', 180);
    }

    public function syncAction()
    {
        if (!$this->request->isPost()) {
            return $this->methodError();
        }
        return $this->runAgent('ofme agent.sync', 600);
    }

    public function previewAction()
    {
        return $this->runAgent('ofme agent.preview', 300);
    }

    public function diagnosticsAction()
    {
        return $this->runAgent('ofme agent.diagnostics', 180);
    }

    public function testAction()
    {
        if (!$this->request->isPost()) {
            return $this->methodError();
        }
        return $this->runAgent('ofme agent.test', 60);
    }

    public function logAction()
    {
        $lines = (int)$this->request->getPost('lines', null, 200);
        if ($lines <= 0) {
            $lines = (int)$this->request->getQuery('lines', null, 200);
        }
        $lines = max(1, min(1000, $lines));

        try {
            $backend = new Backend();
            $response = $backend->configdpRun('ofme agent.log', [$lines], false, 30);
        } catch (\Throwable $exception) {
            return ['status' => 'error', 'count' => 0, 'lines' => [], 'message' => $exception->getMessage()];
        }

        $decoded = json_decode((string)$response, true);
        if (!is_array($decoded)) {
            return [
                'status' => 'error',
                'count' => 0,
                'lines' => [],
                'message' => trim((string)$response) !== ''
                    ? trim((string)$response)
                    : 'The agent did not return a log document.',
            ];
        }

        return $decoded;
    }

    public function commandAction()
    {
        if (!$this->request->isPost()) {
            return $this->methodError();
        }

        $action = strtolower(trim((string)$this->request->getPost('action', null, '')));
        if ($action === '') {
            return ['status' => 'error', 'message' => 'No command action was supplied.'];
        }
        if (!in_array($action, CommandRunner::ACTIONS, true)) {
            return ['status' => 'error', 'message' => 'The command action is not whitelisted.'];
        }

        try {
            $backend = new Backend();
            $response = $backend->configdpRun('ofme agent.command', [$action], false, 600);
        } catch (\Throwable $exception) {
            return ['status' => 'error', 'message' => $exception->getMessage()];
        }

        $decoded = json_decode((string)$response, true);
        if (!is_array($decoded)) {
            return [
                'status' => 'error',
                'message' => trim((string)$response) !== ''
                    ? trim((string)$response)
                    : 'The command did not return a result.',
            ];
        }

        return $decoded;
    }

    public function serviceAction()
    {
        if (!$this->request->isPost()) {
            return $this->methodError();
        }

        $command = strtolower(trim((string)$this->request->getPost('command', null, '')));
        if (!in_array($command, self::SERVICE_COMMANDS, true)) {
            return ['status' => 'error', 'message' => 'Unsupported service command.'];
        }

        try {
            $backend = new Backend();
            $output = $backend->configdRun('ofme ' . $command, false, 90);
        } catch (\Throwable $exception) {
            return ['status' => 'error', 'message' => $exception->getMessage()];
        }

        return [
            'status' => 'ok',
            'command' => $command,
            'output' => trim((string)$output),
            'timestamp' => gmdate('c'),
        ];
    }

    public function resetAction()
    {
        if (!$this->request->isPost()) {
            return $this->methodError();
        }

        $confirm = $this->request->getPost('confirm', null, '');
        if (!in_array($confirm, ['yes', '1', 1, true], true)) {
            return [
                'status' => 'error',
                'message' => 'Resetting the enrollment requires confirm=yes.',
            ];
        }

        $result = $this->runAgent('ofme agent.reset', 60);
        try {
            (new Backend())->configdRun('ofme stop', true);
        } catch (\Throwable $exception) {
            $result['service_warning'] = $exception->getMessage();
        }
        return $result;
    }

    /**
     * @return array<string, mixed>
     */
    private function runAgent(string $action, int $timeout): array
    {
        try {
            $backend = new Backend();
            $response = $backend->configdRun($action, false, $timeout);
        } catch (\Throwable $exception) {
            return [
                'status' => 'error',
                'message' => $exception->getMessage(),
                'timestamp' => gmdate('c'),
            ];
        }

        $decoded = json_decode((string)$response, true);
        if (!is_array($decoded)) {
            return [
                'status' => 'error',
                'message' => trim((string)$response) !== ''
                    ? trim((string)$response)
                    : 'The agent did not return a JSON document.',
                'timestamp' => gmdate('c'),
            ];
        }

        return $decoded;
    }

    /**
     * @return array<string, string>
     */
    private function methodError(): array
    {
        return [
            'status' => 'error',
            'message' => 'This operation requires an HTTP POST request.',
        ];
    }
}
