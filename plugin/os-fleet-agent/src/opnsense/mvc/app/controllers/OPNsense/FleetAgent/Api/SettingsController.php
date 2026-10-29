<?php

namespace OPNsense\FleetAgent\Api;

use OPNsense\Base\ApiMutableModelControllerBase;
use OPNsense\Core\Backend;

/**
 * Settings, status, log and trust-anchor API for the OFME Fleet Agent.
 *
 * Privileged operations are executed through configd so that the web process
 * never has to read the agent's root-only key directory.
 */
class SettingsController extends ApiMutableModelControllerBase
{
    protected static $internalModelClass = 'OPNsense\FleetAgent\Settings';
    protected static $internalModelName = 'fleetagent';

    public function setAction()
    {
        $result = parent::setAction();

        if (($result['result'] ?? '') === 'saved') {
            $model = $this->getModel();
            $backend = new Backend();
            try {
                if ((string)$model->enabled === '1') {
                    $backend->configdRun('ofme restart', true);
                } else {
                    $backend->configdRun('ofme stop', true);
                }
            } catch (\Throwable $exception) {
                $result['service_warning'] = 'Settings were saved but the service action failed: '
                    . $exception->getMessage();
            }
        }

        return $result;
    }

    /**
     * Live status reported by the agent process.
     */
    public function statusAction()
    {
        try {
            $backend = new Backend();
            $response = $backend->configdRun('ofme agent.status', false, 30);
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
                    : 'The agent did not return a status document.',
                'timestamp' => gmdate('c'),
            ];
        }

        return $decoded;
    }

    /**
     * Bounded, structured log tail.
     */
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
            return [
                'status' => 'error',
                'count' => 0,
                'lines' => [],
                'message' => $exception->getMessage(),
            ];
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

    /**
     * Collect a diagnostics bundle on the firewall.
     */
    public function diagnosticsAction()
    {
        try {
            $backend = new Backend();
            $response = $backend->configdRun('ofme agent.diagnostics', false, 180);
        } catch (\Throwable $exception) {
            return ['status' => 'error', 'message' => $exception->getMessage()];
        }

        $decoded = json_decode((string)$response, true);
        if (!is_array($decoded)) {
            return [
                'status' => 'error',
                'message' => trim((string)$response) !== ''
                    ? trim((string)$response)
                    : 'Unable to collect diagnostics.',
            ];
        }

        return $decoded;
    }

    /**
     * Import and pin the platform CA certificate.
     *
     * The PEM is written to a short-lived root-owned hand-off file. The CLI
     * validates that the path is inside the temporary directory and that the
     * file name carries the OFME prefix before it installs the CA.
     */
    public function importCAAction()
    {
        $pem = trim((string)$this->request->getPost('pem', null, ''));
        if ($pem === '') {
            $pem = trim((string)$this->request->getPost('ca_pem', null, ''));
        }
        if ($pem === '') {
            return ['status' => 'error', 'message' => 'No PEM certificate was supplied.'];
        }
        if (strlen($pem) > 1048576) {
            return ['status' => 'error', 'message' => 'The CA bundle is larger than 1 MiB.'];
        }
        if (!str_contains($pem, '-----BEGIN CERTIFICATE-----')) {
            return ['status' => 'error', 'message' => 'The supplied data is not a PEM certificate.'];
        }

        $temporary = tempnam(sys_get_temp_dir(), 'ofme-ca-');
        if ($temporary === false) {
            return ['status' => 'error', 'message' => 'Unable to create a temporary file.'];
        }
        @chmod($temporary, 0600);
        if (@file_put_contents($temporary, $pem . PHP_EOL) === false) {
            @unlink($temporary);
            return ['status' => 'error', 'message' => 'Unable to write the temporary CA file.'];
        }

        try {
            $backend = new Backend();
            $response = $backend->configdpRun('ofme agent.import-ca', [$temporary], false, 60);
        } catch (\Throwable $exception) {
            @unlink($temporary);
            return ['status' => 'error', 'message' => $exception->getMessage()];
        } finally {
            @unlink($temporary);
        }

        $decoded = json_decode((string)$response, true);
        if (!is_array($decoded)) {
            return [
                'status' => 'error',
                'message' => trim((string)$response) !== ''
                    ? trim((string)$response)
                    : 'The CA could not be imported.',
            ];
        }

        return $decoded;
    }
}
