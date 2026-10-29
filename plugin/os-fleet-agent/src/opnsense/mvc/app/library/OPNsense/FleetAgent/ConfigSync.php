<?php

namespace OPNsense\FleetAgent;

use OPNsense\Core\Config;
use OPNsense\Firewall\Alias;
use OPNsense\Firewall\Filter;

/**
 * Desired-state synchronisation for aliases and firewall rules.
 *
 * Only objects whose description starts with the OFME- marker are ever
 * created, modified or deleted. Everything else on the firewall is left
 * untouched. Aliases are applied first and pruned last so that a rule can
 * always reference an alias that already exists during validation.
 *
 * NAT, interfaces, routes, VLANs, VPN and SD-WAN data is never written by the
 * agent; it is compared with the local configuration and reported as drift.
 */
final class ConfigSync
{
    public const MARKER = 'OFME-';

    private const ALIAS_TYPES = [
        'host' => 'host',
        'network' => 'network',
        'port' => 'port',
        'url' => 'url',
        'mac' => 'mac',
        'nested' => 'networkgroup',
        'networkgroup' => 'networkgroup',
    ];

    private const RULE_ACTIONS = ['pass', 'block', 'reject'];
    private const RULE_DIRECTIONS = ['in', 'out', 'any'];
    private const MAX_ALIAS_ENTRIES = 1000;
    private const MAX_DESCRIPTION = 255;

    private AgentClient $client;

    public function __construct(private AgentConfig $config, ?AgentClient $client = null)
    {
        $this->client = $client ?? new AgentClient($config, new Identity());
    }

    /**
     * Fetch the desired configuration document.
     *
     * @return array<string, mixed>
     */
    public function fetchDesired(): array
    {
        if (!$this->config->enabled()) {
            throw new \RuntimeException('The OFME Fleet Agent is disabled.');
        }
        if ($this->config->deviceId() === '') {
            throw new \RuntimeException('The device is not enrolled.');
        }

        $response = $this->client->desiredConfig();
        if ($response['status'] !== 200 || !is_array($response['json'])) {
            throw new \RuntimeException(
                'Unable to fetch the desired configuration: ' . (new Enrollment($this->config))->describe($response)
            );
        }

        $payload = $response['json'];
        if (!isset($payload['config_hash']) || !is_string($payload['config_hash'])) {
            throw new \RuntimeException('The platform response is missing config_hash.');
        }

        $encoded = json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
        if ($encoded === false) {
            throw new \RuntimeException('Unable to encode the desired configuration.');
        }
        Paths::write(Paths::DESIRED_FILE, $encoded . PHP_EOL, 0600);
        State::merge([
            'desired_hash' => $payload['config_hash'],
            'desired_fetched_at' => gmdate('c'),
            'desired_generated_at' => $payload['generated_at'] ?? null,
        ]);

        return $payload;
    }

    /**
     * Compute the difference between desired and local state without writing.
     *
     * @return array<string, mixed>
     */
    public function preview(): array
    {
        $desired = $this->fetchDesired();
        $aliases = $this->planAliases($desired['aliases'] ?? []);
        $rules = $this->planRules($desired['firewall_rules'] ?? []);

        return [
            'config_hash' => $desired['config_hash'],
            'generated_at' => $desired['generated_at'] ?? null,
            'apply_aliases' => $this->config->applyAliases(),
            'apply_firewall_rules' => $this->config->applyFirewallRules(),
            'aliases' => $aliases,
            'firewall_rules' => $rules,
            'drift' => $this->computeDrift($desired),
        ];
    }

    /**
     * Apply the desired configuration to the firewall.
     *
     * @return array<string, mixed>
     */
    public function sync(bool $force = false): array
    {
        $started = microtime(true);
        $desired = $this->fetchDesired();
        $hash = (string)$desired['config_hash'];
        $managed = $this->loadManaged();

        $applyAliases = $this->config->applyAliases();
        $applyRules = $this->config->applyFirewallRules();

        $report = [
            'config_hash' => $hash,
            'generated_at' => $desired['generated_at'] ?? null,
            'started_at' => gmdate('c'),
            'apply_aliases' => $applyAliases,
            'apply_firewall_rules' => $applyRules,
            'skipped' => false,
            'aliases' => $this->planAliases($desired['aliases'] ?? []),
            'firewall_rules' => $this->planRules($desired['firewall_rules'] ?? []),
            'drift' => [],
            'errors' => [],
            'reload' => null,
        ];

        $unchanged = !$force
            && ($managed['config_hash'] ?? null) === $hash
            && ($managed['apply_aliases'] ?? false) === $applyAliases
            && ($managed['apply_firewall_rules'] ?? false) === $applyRules;

        if ($unchanged) {
            $report['skipped'] = true;
            $report['drift'] = $this->computeDrift($desired);
            $report['finished_at'] = gmdate('c');
            $report['duration_ms'] = (int)round((microtime(true) - $started) * 1000);
            $report['status'] = 'unchanged';
            $this->writeApplyReport($report);
            return $report;
        }

        $aliasChanged = false;
        if ($applyAliases) {
            try {
                $aliasResult = $this->applyAliases($desired['aliases'] ?? [], false);
                $report['aliases'] = $aliasResult;
                $aliasChanged = $aliasResult['changed'];
            } catch (\Throwable $exception) {
                Logger::exception($exception, 'Alias synchronisation failed');
                $report['errors'][] = 'aliases: ' . $exception->getMessage();
            }
        }

        $rulesChanged = false;
        if ($applyRules) {
            if ($applyAliases && $report['errors'] !== []) {
                $report['errors'][] = 'firewall_rules: skipped because alias synchronisation failed';
            } else {
                try {
                    $ruleResult = $this->applyRules($desired['firewall_rules'] ?? []);
                    $report['firewall_rules'] = $ruleResult;
                    $rulesChanged = $ruleResult['changed'];
                } catch (\Throwable $exception) {
                    Logger::exception($exception, 'Firewall rule synchronisation failed');
                    $report['errors'][] = 'firewall_rules: ' . $exception->getMessage();
                }
            }
        }

        if ($applyAliases && $report['errors'] === []) {
            try {
                $pruned = $this->pruneAliases($desired['aliases'] ?? []);
                if ($pruned['deleted'] !== []) {
                    $aliasChanged = true;
                    $report['aliases']['delete'] = array_values(
                        array_unique(array_merge($report['aliases']['delete'], $pruned['deleted']))
                    );
                    $report['aliases']['changed'] = true;
                }
                if ($pruned['blocked'] !== []) {
                    foreach ($pruned['blocked'] as $blocked) {
                        $report['aliases']['conflicts'][] = $blocked;
                    }
                }
            } catch (\Throwable $exception) {
                Logger::exception($exception, 'Alias pruning failed');
                $report['errors'][] = 'aliases: ' . $exception->getMessage();
            }
        }

        if ($aliasChanged || $rulesChanged) {
            $report['reload'] = $this->reloadFilter();
        }

        $report['drift'] = $this->computeDrift($desired);
        $this->storeManaged($desired, $report['aliases'], $report['firewall_rules'], $applyAliases, $applyRules);
        $report['finished_at'] = gmdate('c');
        $report['duration_ms'] = (int)round((microtime(true) - $started) * 1000);
        $report['status'] = $report['errors'] === [] ? 'applied' : 'partial';
        $this->writeApplyReport($report);

        State::merge([
            'last_config_hash' => $hash,
            'last_config_applied_at' => gmdate('c'),
            'last_apply_status' => $report['status'],
        ]);

        Logger::info('Desired configuration synchronised', [
            'config_hash' => $hash,
            'status' => $report['status'],
            'aliases_changed' => $aliasChanged,
            'rules_changed' => $rulesChanged,
            'errors' => count($report['errors']),
        ]);

        return $report;
    }

    /**
     * @param list<array<string, mixed>> $desiredAliases
     * @return array<string, mixed>
     */
    private function applyAliases(array $desiredAliases, bool $prune): array
    {
        $plan = [
            'create' => [],
            'update' => [],
            'unchanged' => [],
            'delete' => [],
            'conflicts' => [],
            'changed' => false,
        ];

        Config::getInstance()->lock();
        try {
            $model = new Alias();
            $existing = $this->indexAliases($model);
            $desiredNames = [];

            foreach ($desiredAliases as $row) {
                if (!is_array($row)) {
                    $plan['conflicts'][] = ['name' => '', 'reason' => 'invalid alias record'];
                    continue;
                }
                $name = trim((string)($row['name'] ?? ''));
                if (!$this->validAliasName($name)) {
                    $plan['conflicts'][] = [
                        'name' => $name,
                        'reason' => 'the alias name is not a valid OPNsense alias identifier',
                    ];
                    continue;
                }
                if (isset($desiredNames[$name])) {
                    $plan['conflicts'][] = [
                        'name' => $name,
                        'reason' => 'duplicate alias name in the desired configuration',
                    ];
                    continue;
                }
                $desiredNames[$name] = true;

                $type = $this->aliasType((string)($row['type'] ?? 'host'));
                $content = $this->aliasContent($row['content'] ?? []);
                $enabled = (bool)($row['enabled'] ?? true);
                $description = $this->aliasDescription($row);

                if (!isset($existing[$name])) {
                    $node = $model->aliases->alias->Add();
                    $this->writeAlias($node, $name, $type, $content, $enabled, $description);
                    $plan['create'][] = $name;
                    continue;
                }

                $current = $existing[$name];
                if (!$this->isManagedDescription($current['description'])) {
                    $plan['conflicts'][] = [
                        'name' => $name,
                        'reason' => 'an alias with this name exists but is not managed by OFME',
                    ];
                    continue;
                }

                if ($this->aliasMatches($current['node'], $type, $content, $enabled, $description)) {
                    $plan['unchanged'][] = $name;
                    continue;
                }

                $this->writeAlias($current['node'], $name, $type, $content, $enabled, $description);
                $plan['update'][] = $name;
            }

            if ($prune) {
                foreach ($existing as $name => $item) {
                    if (isset($desiredNames[$name])) {
                        continue;
                    }
                    if (!$this->isManagedDescription($item['description'])) {
                        continue;
                    }
                    if ($this->aliasInUse($model, $name)) {
                        $plan['conflicts'][] = [
                            'name' => $name,
                            'reason' => 'the alias is still referenced by a non-managed rule',
                        ];
                        continue;
                    }
                    $model->aliases->alias->del($item['uuid']);
                    $plan['delete'][] = $name;
                }
            }

            $plan['changed'] = $plan['create'] !== []
                || $plan['update'] !== []
                || $plan['delete'] !== [];

            if ($plan['changed']) {
                $model->serializeToConfig(false, false);
                Config::getInstance()->save();
            } else {
                Config::getInstance()->unlock();
            }
        } catch (\Throwable $exception) {
            Config::getInstance()->unlock();
            throw $exception;
        }

        return $plan;
    }

    /**
     * @param list<array<string, mixed>> $desiredAliases
     * @return array<string, mixed>
     */
    private function pruneAliases(array $desiredAliases): array
    {
        $result = ['deleted' => [], 'blocked' => []];

        Config::getInstance()->lock();
        try {
            $model = new Alias();
            $desiredNames = [];
            foreach ($desiredAliases as $row) {
                if (is_array($row)) {
                    $desiredNames[trim((string)($row['name'] ?? ''))] = true;
                }
            }

            foreach ($this->indexAliases($model) as $name => $item) {
                if (isset($desiredNames[$name]) || !$this->isManagedDescription($item['description'])) {
                    continue;
                }
                if ($this->aliasInUse($model, $name)) {
                    $result['blocked'][] = [
                        'name' => $name,
                        'reason' => 'the alias is still referenced by a non-managed rule',
                    ];
                    continue;
                }
                $model->aliases->alias->del($item['uuid']);
                $result['deleted'][] = $name;
            }

            if ($result['deleted'] !== []) {
                $model->serializeToConfig(false, false);
                Config::getInstance()->save();
            } else {
                Config::getInstance()->unlock();
            }
        } catch (\Throwable $exception) {
            Config::getInstance()->unlock();
            throw $exception;
        }

        return $result;
    }

    /**
     * @param list<array<string, mixed>> $desiredRules
     * @return array<string, mixed>
     */
    private function applyRules(array $desiredRules): array
    {
        $plan = [
            'create' => [],
            'update' => [],
            'unchanged' => [],
            'delete' => [],
            'conflicts' => [],
            'changed' => false,
        ];

        Config::getInstance()->lock();
        try {
            $model = new Filter();
            $existing = $this->indexRules($model);
            $desiredKeys = [];

            foreach ($desiredRules as $row) {
                if (!is_array($row)) {
                    $plan['conflicts'][] = ['name' => '', 'reason' => 'invalid firewall rule record'];
                    continue;
                }
                $key = $this->ruleKey($row);
                if ($key === '') {
                    $plan['conflicts'][] = ['name' => '', 'reason' => 'the rule has no usable name'];
                    continue;
                }
                if (isset($desiredKeys[$key])) {
                    $plan['conflicts'][] = [
                        'name' => (string)($row['name'] ?? ''),
                        'reason' => 'duplicate firewall rule name in the desired configuration',
                    ];
                    continue;
                }
                $desiredKeys[$key] = true;

                $signature = $this->ruleSignature($row);
                if ($signature === null) {
                    $plan['conflicts'][] = [
                        'name' => (string)($row['name'] ?? ''),
                        'reason' => 'the rule uses an unsupported action, direction or protocol',
                    ];
                    continue;
                }

                if (!isset($existing[$key])) {
                    $node = $model->rules->rule->Add();
                    $this->writeRule($node, $row, $signature, true);
                    $plan['create'][] = $signature['name'];
                    continue;
                }

                $current = $existing[$key];
                if ($this->ruleMatches($current['node'], $signature)) {
                    $plan['unchanged'][] = $signature['name'];
                    continue;
                }
                $this->writeRule($current['node'], $row, $signature, false);
                $plan['update'][] = $signature['name'];
            }

            foreach ($existing as $key => $item) {
                if (isset($desiredKeys[$key])) {
                    continue;
                }
                $model->rules->rule->del($item['uuid']);
                $plan['delete'][] = $item['name'];
            }

            $plan['changed'] = $plan['create'] !== []
                || $plan['update'] !== []
                || $plan['delete'] !== [];

            if ($plan['changed']) {
                $model->serializeToConfig(false, false);
                Config::getInstance()->save();
            } else {
                Config::getInstance()->unlock();
            }
        } catch (\Throwable $exception) {
            Config::getInstance()->unlock();
            throw $exception;
        }

        return $plan;
    }

    /**
     * Read-only alias plan used by preview().
     *
     * @param mixed $desiredAliases
     * @return array<string, mixed>
     */
    private function planAliases($desiredAliases): array
    {
        $plan = [
            'create' => [],
            'update' => [],
            'unchanged' => [],
            'delete' => [],
            'conflicts' => [],
            'changed' => false,
        ];
        if (!is_array($desiredAliases)) {
            return $plan;
        }

        $model = new Alias();
        $existing = $this->indexAliases($model);
        $desiredNames = [];

        foreach ($desiredAliases as $row) {
            if (!is_array($row)) {
                continue;
            }
            $name = trim((string)($row['name'] ?? ''));
            if (!$this->validAliasName($name)) {
                $plan['conflicts'][] = ['name' => $name, 'reason' => 'invalid OPNsense alias name'];
                continue;
            }
            if (isset($desiredNames[$name])) {
                $plan['conflicts'][] = ['name' => $name, 'reason' => 'duplicate alias name'];
                continue;
            }
            $desiredNames[$name] = true;

            $type = $this->aliasType((string)($row['type'] ?? 'host'));
            $content = $this->aliasContent($row['content'] ?? []);
            $enabled = (bool)($row['enabled'] ?? true);
            $description = $this->aliasDescription($row);

            if (!isset($existing[$name])) {
                $plan['create'][] = $name;
                continue;
            }
            if (!$this->isManagedDescription($existing[$name]['description'])) {
                $plan['conflicts'][] = [
                    'name' => $name,
                    'reason' => 'an alias with this name exists but is not managed by OFME',
                ];
                continue;
            }
            if ($this->aliasMatches($existing[$name]['node'], $type, $content, $enabled, $description)) {
                $plan['unchanged'][] = $name;
            } else {
                $plan['update'][] = $name;
            }
        }

        foreach ($existing as $name => $item) {
            if (isset($desiredNames[$name]) || !$this->isManagedDescription($item['description'])) {
                continue;
            }
            $plan['delete'][] = $name;
        }

        $plan['changed'] = $plan['create'] !== [] || $plan['update'] !== [] || $plan['delete'] !== [];
        return $plan;
    }

    /**
     * Read-only rule plan used by preview().
     *
     * @param mixed $desiredRules
     * @return array<string, mixed>
     */
    private function planRules($desiredRules): array
    {
        $plan = [
            'create' => [],
            'update' => [],
            'unchanged' => [],
            'delete' => [],
            'conflicts' => [],
            'changed' => false,
        ];
        if (!is_array($desiredRules)) {
            return $plan;
        }

        $model = new Filter();
        $existing = $this->indexRules($model);
        $desiredKeys = [];

        foreach ($desiredRules as $row) {
            if (!is_array($row)) {
                continue;
            }
            $key = $this->ruleKey($row);
            $signature = $this->ruleSignature($row);
            if ($key === '' || $signature === null) {
                $plan['conflicts'][] = [
                    'name' => (string)($row['name'] ?? ''),
                    'reason' => 'invalid or unsupported rule',
                ];
                continue;
            }
            if (isset($desiredKeys[$key])) {
                $plan['conflicts'][] = [
                    'name' => $signature['name'],
                    'reason' => 'duplicate firewall rule name',
                ];
                continue;
            }
            $desiredKeys[$key] = true;

            if (!isset($existing[$key])) {
                $plan['create'][] = $signature['name'];
            } elseif ($this->ruleMatches($existing[$key]['node'], $signature)) {
                $plan['unchanged'][] = $signature['name'];
            } else {
                $plan['update'][] = $signature['name'];
            }
        }

        foreach ($existing as $key => $item) {
            if (!isset($desiredKeys[$key])) {
                $plan['delete'][] = $item['name'];
            }
        }

        $plan['changed'] = $plan['create'] !== [] || $plan['update'] !== [] || $plan['delete'] !== [];
        return $plan;
    }

    /**
     * Compare desired non-applied sections with the local configuration.
     *
     * @param array<string, mixed> $desired
     * @return list<array<string, mixed>>
     */
    private function computeDrift(array $desired): array
    {
        $config = Config::getInstance()->object();
        $drift = [];

        $drift[] = $this->driftSection(
            'nat',
            count(is_array($desired['nat'] ?? null) ? $desired['nat'] : []),
            $this->localNatCount($config),
            'NAT rules are reported only and never written by the agent.'
        );
        $drift[] = $this->driftSection(
            'interfaces',
            count(is_array($desired['interfaces'] ?? null) ? $desired['interfaces'] : []),
            count($this->localInterfaceNames($config)),
            'Interface configuration is reported only; it is not applied automatically.'
        );
        $drift[] = $this->driftSection(
            'routes',
            count(is_array($desired['routes'] ?? null) ? $desired['routes'] : []),
            $this->localRouteCount($config),
            'Static routes are reported only and never written by the agent.'
        );
        $drift[] = $this->driftSection(
            'vlans',
            count(is_array($desired['vlans'] ?? null) ? $desired['vlans'] : []),
            $this->localVlanCount($config),
            'VLANs are reported only and never written by the agent.'
        );
        $drift[] = $this->driftSection(
            'vpn',
            count(is_array($desired['vpn'] ?? null) ? $desired['vpn'] : []),
            $this->localVpnCount($config),
            'VPN tunnels are reported only; WireGuard, IPsec and OpenVPN are managed elsewhere.'
        );
        $drift[] = $this->driftSection(
            'sdwan_routes',
            count(is_array($desired['sdwan_routes'] ?? null) ? $desired['sdwan_routes'] : []),
            $this->localRouteCount($config),
            'SD-WAN routes are reported only and never written by the agent.'
        );

        $desiredPolicies = is_array($desired['policies'] ?? null) ? $desired['policies'] : [];
        $policyHash = hash('sha256', json_encode($desiredPolicies, JSON_UNESCAPED_SLASHES) ?: '');
        $drift[] = [
            'section' => 'policies',
            'status' => 'informational',
            'desired' => count($desiredPolicies),
            'actual' => null,
            'message' => 'Deployed policies are available in the desired configuration and are applied through rules and aliases.',
            'signature' => $policyHash,
        ];

        return $drift;
    }

    /**
     * @param \SimpleXMLElement $config
     * @return array<string, mixed>
     */
    private function driftSection(string $section, int $desired, int $actual, string $message): array
    {
        return [
            'section' => $section,
            'status' => $desired === $actual ? 'in_sync' : 'drift',
            'desired' => $desired,
            'actual' => $actual,
            'message' => $message,
        ];
    }

    /**
     * @return array<string, array{uuid: string, node: mixed, description: string}>
     */
    private function indexAliases(Alias $model): array
    {
        $result = [];
        foreach ($model->aliases->alias->iterateItems() as $uuid => $node) {
            $name = (string)$node->name;
            if ($name === '') {
                continue;
            }
            $result[$name] = [
                'uuid' => (string)$uuid,
                'node' => $node,
                'description' => (string)$node->description,
            ];
        }
        return $result;
    }

    /**
     * @return array<string, array{uuid: string, node: mixed, name: string}>
     */
    private function indexRules(Filter $model): array
    {
        $result = [];
        foreach ($model->rules->rule->iterateItems() as $uuid => $node) {
            $description = (string)$node->description;
            if (!$this->isManagedDescription($description)) {
                continue;
            }
            $name = trim(substr($description, strlen(self::MARKER)));
            if ($name === '') {
                continue;
            }
            $result[$this->normaliseKey($name)] = [
                'uuid' => (string)$uuid,
                'node' => $node,
                'name' => $name,
            ];
        }
        return $result;
    }

    private function writeAlias(
        $node,
        string $name,
        string $type,
        string $content,
        bool $enabled,
        string $description
    ): void {
        $node->enabled = $enabled ? '1' : '0';
        $node->name = $name;
        $node->type = $type;
        $node->content = $content;
        $node->description = $description;
    }

    private function aliasMatches(
        $node,
        string $type,
        string $content,
        bool $enabled,
        string $description
    ): bool {
        $currentContent = str_replace("\r\n", "\n", (string)$node->content);
        $currentContent = implode("\n", array_values(array_filter(
            array_map('trim', explode("\n", $currentContent)),
            static fn(string $value): bool => $value !== ''
        )));

        return (string)$node->type === $type
            && $currentContent === $content
            && (string)$node->enabled === ($enabled ? '1' : '0')
            && trim((string)$node->description) === $description;
    }

    /**
     * @param array<string, mixed> $row
     * @return array<string, string>|null
     */
    private function ruleSignature(array $row): ?array
    {
        $name = trim((string)($row['name'] ?? ''));
        if ($name === '') {
            return null;
        }
        $action = strtolower(trim((string)($row['action'] ?? 'block')));
        if (!in_array($action, self::RULE_ACTIONS, true)) {
            return null;
        }
        $direction = strtolower(trim((string)($row['direction'] ?? 'in')));
        if (!in_array($direction, self::RULE_DIRECTIONS, true)) {
            return null;
        }

        $interface = trim((string)($row['interface'] ?? ''));
        if ($interface !== '' && !preg_match('/^[A-Za-z0-9_.]+$/', $interface)) {
            return null;
        }

        $protocol = $this->normaliseProtocol((string)($row['protocol'] ?? 'any'));
        if ($protocol === null) {
            return null;
        }

        $source = $this->normaliseNetwork((string)($row['source'] ?? 'any'));
        $destination = $this->normaliseNetwork((string)($row['destination'] ?? 'any'));

        return [
            'name' => $name,
            'key' => $this->normaliseKey($name),
            'action' => $action,
            'direction' => $direction,
            'interface' => $interface === '' ? 'floating' : $interface,
            'protocol' => $protocol,
            'ipprotocol' => $this->inferIpProtocol($source, $destination, $protocol),
            'source' => $source,
            'destination' => $destination,
            'source_port' => trim((string)($row['source_port'] ?? '')),
            'destination_port' => trim((string)($row['destination_port'] ?? '')),
            'gateway' => trim((string)($row['gateway'] ?? '')),
            'log' => !empty($row['log']) ? '1' : '0',
            'enabled' => !isset($row['enabled']) || (bool)$row['enabled'] ? '1' : '0',
        ];
    }

    /**
     * @param array<string, string> $signature
     */
    private function writeRule($node, array $row, array $signature, bool $isNew): void
    {
        $node->enabled = $signature['enabled'];
        $node->action = $signature['action'];
        $node->direction = $signature['direction'];
        $node->interface = $signature['interface'] === 'floating' ? '' : $signature['interface'];
        $node->ipprotocol = $signature['ipprotocol'];
        $node->protocol = $signature['protocol'];
        $node->source_net = $signature['source'];
        $node->destination_net = $signature['destination'];
        $node->source_port = $signature['source_port'];
        $node->destination_port = $signature['destination_port'];
        $node->gateway = $signature['gateway'];
        $node->log = $signature['log'];
        $node->quick = '1';
        $node->description = $this->ruleDescription($signature['name']);

        if ($isNew) {
            $order = (int)($row['order_index'] ?? 0);
            if ($order > 0) {
                $node->sequence = (string)max(1, min(999999, $order));
            }
        }
    }

    private function ruleMatches($node, array $signature): bool
    {
        $current = [
            'action' => strtolower((string)$node->action),
            'direction' => strtolower((string)$node->direction),
            'interface' => trim((string)$node->interface) === '' ? 'floating' : trim((string)$node->interface),
            'protocol' => (string)$node->protocol,
            'ipprotocol' => (string)$node->ipprotocol,
            'source' => $this->normaliseNetwork((string)$node->source_net),
            'destination' => $this->normaliseNetwork((string)$node->destination_net),
            'source_port' => trim((string)$node->source_port),
            'destination_port' => trim((string)$node->destination_port),
            'gateway' => trim((string)$node->gateway),
            'log' => (string)$node->log === '1' ? '1' : '0',
            'enabled' => (string)$node->enabled === '1' ? '1' : '0',
        ];

        foreach ($current as $field => $value) {
            if (($signature[$field] ?? null) !== $value) {
                return false;
            }
        }
        return trim((string)$node->description) === $this->ruleDescription($signature['name']);
    }

    private function normaliseProtocol(string $value): ?string
    {
        $value = strtolower(trim($value));
        $map = [
            '' => 'any',
            'any' => 'any',
            'tcp' => 'TCP',
            'udp' => 'UDP',
            'tcp/udp' => 'TCP/UDP',
            'icmp' => 'ICMP',
            'icmp6' => 'IPV6-ICMP',
            'ipv6-icmp' => 'IPV6-ICMP',
            'esp' => 'ESP',
            'ah' => 'AH',
            'gre' => 'GRE',
            'igmp' => 'IGMP',
            'pim' => 'PIM',
            'ospf' => 'OSPF',
        ];
        if (isset($map[$value])) {
            return $map[$value];
        }
        if (preg_match('/^[a-z0-9-]{1,16}$/', $value)) {
            return strtoupper($value);
        }
        return null;
    }

    private function inferIpProtocol(string $source, string $destination, string $protocol): string
    {
        if ($protocol === 'IPV6-ICMP') {
            return 'inet6';
        }

        $families = [];
        foreach ([$source, $destination] as $value) {
            foreach (explode(',', $value) as $entry) {
                $entry = trim($entry);
                if ($entry === '' || $entry === 'any' || !preg_match('/^[0-9a-fA-F:.\/]+$/', $entry)) {
                    continue;
                }
                if (str_contains($entry, ':')) {
                    $families['inet6'] = true;
                } elseif (str_contains($entry, '.') || ctype_digit($entry)) {
                    $families['inet'] = true;
                }
            }
        }

        if (isset($families['inet'], $families['inet6'])) {
            return 'inet46';
        }
        if (isset($families['inet6'])) {
            return 'inet6';
        }
        return 'inet';
    }

    private function normaliseNetwork(string $value): string
    {
        $value = trim($value);
        if ($value === '') {
            return 'any';
        }
        $parts = array_values(array_filter(
            array_map('trim', explode(',', $value)),
            static fn(string $entry): bool => $entry !== ''
        ));
        if ($parts === []) {
            return 'any';
        }
        return implode(',', $parts);
    }

    private function aliasType(string $value): string
    {
        $value = strtolower(trim($value));
        return self::ALIAS_TYPES[$value] ?? 'host';
    }

    /**
     * @param mixed $content
     */
    private function aliasContent($content): string
    {
        if (is_string($content)) {
            $content = preg_split('/[\r\n,]+/', $content) ?: [];
        }
        if (!is_array($content)) {
            return '';
        }
        $entries = [];
        foreach ($content as $entry) {
            if (!is_scalar($entry)) {
                continue;
            }
            $entry = trim((string)$entry);
            if ($entry === '') {
                continue;
            }
            $entries[] = $entry;
            if (count($entries) >= self::MAX_ALIAS_ENTRIES) {
                break;
            }
        }
        return implode("\n", $entries);
    }

    /**
     * @param array<string, mixed> $row
     */
    private function aliasDescription(array $row): string
    {
        $description = trim((string)($row['description'] ?? ''));
        if ($description === '') {
            $description = trim((string)($row['name'] ?? ''));
        }
        return $this->sanitiseDescription(self::MARKER . $description);
    }

    private function ruleDescription(string $name): string
    {
        return $this->sanitiseDescription(self::MARKER . $name);
    }

    private function sanitiseDescription(string $value): string
    {
        $value = preg_replace('/[^\t\n\v\f\r 0-9a-zA-Z.\-,_\x{00A0}-\x{FFFF}]/u', ' ', $value) ?? $value;
        $value = preg_replace('/\s+/u', ' ', $value) ?? $value;
        $value = trim($value);
        if (function_exists('mb_substr')) {
            return mb_substr($value, 0, self::MAX_DESCRIPTION);
        }
        return substr($value, 0, self::MAX_DESCRIPTION);
    }

    private function isManagedDescription(string $description): bool
    {
        return str_starts_with(trim($description), self::MARKER);
    }

    private function validAliasName(string $name): bool
    {
        return (bool)preg_match('/^[A-Za-z_][A-Za-z0-9_]{0,30}$/', $name);
    }

    private function normaliseKey(string $name): string
    {
        return strtolower(trim($name));
    }

    /**
     * @param array<string, mixed> $row
     */
    private function ruleKey(array $row): string
    {
        $signature = $this->ruleSignature($row);
        return $signature['key'] ?? '';
    }

    private function aliasInUse(Alias $model, string $name): bool
    {
        try {
            return $model->whereUsed($name) !== [];
        } catch (\Throwable $exception) {
            Logger::debug('Unable to determine alias usage', ['alias' => $name, 'error' => $exception->getMessage()]);
            return true;
        }
    }

    /**
     * @return array<string, mixed>
     */
    private function reloadFilter(): array
    {
        $reload = Configd::run('filter', 'reload', [], 90);
        if (!$reload['ok']) {
            Logger::warning('Filter reload failed', [
                'code' => $reload['code'],
                'stderr' => $reload['stderr'],
            ]);
            return [
                'ok' => false,
                'message' => trim($reload['stderr']) !== '' ? $reload['stderr'] : 'filter reload failed',
            ];
        }
        Configd::run('filter', 'refresh_aliases', [], 90);
        return ['ok' => true, 'message' => 'filter reloaded'];
    }

    /**
     * @return array<string, mixed>
     */
    private function loadManaged(): array
    {
        $raw = Paths::read(Paths::MANAGED_FILE);
        if ($raw === null || trim($raw) === '') {
            return [];
        }
        $decoded = json_decode($raw, true);
        return is_array($decoded) ? $decoded : [];
    }

    /**
     * @param array<string, mixed> $desired
     * @param array<string, mixed> $aliasPlan
     * @param array<string, mixed> $rulePlan
     */
    private function storeManaged(
        array $desired,
        array $aliasPlan,
        array $rulePlan,
        bool $applyAliases,
        bool $applyRules
    ): void {
        $managed = [
            'config_hash' => $desired['config_hash'] ?? null,
            'generated_at' => $desired['generated_at'] ?? null,
            'updated_at' => gmdate('c'),
            'apply_aliases' => $applyAliases,
            'apply_firewall_rules' => $applyRules,
            'aliases' => [],
            'rules' => [],
        ];

        try {
            $aliasModel = new Alias();
            foreach ($this->indexAliases($aliasModel) as $name => $item) {
                if ($this->isManagedDescription($item['description'])) {
                    $managed['aliases'][$name] = $item['uuid'];
                }
            }
            $ruleModel = new Filter();
            foreach ($this->indexRules($ruleModel) as $key => $item) {
                $managed['rules'][$key] = $item['uuid'];
            }
        } catch (\Throwable $exception) {
            Logger::exception($exception, 'Unable to record managed objects');
        }

        $encoded = json_encode($managed, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
        if ($encoded !== false) {
            Paths::write(Paths::MANAGED_FILE, $encoded . PHP_EOL, 0600);
        }
    }

    /**
     * @param array<string, mixed> $report
     */
    private function writeApplyReport(array $report): void
    {
        $encoded = json_encode($report, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
        if ($encoded !== false) {
            Paths::write(Paths::APPLY_FILE, $encoded . PHP_EOL, 0600);
        }
        State::set('last_apply_report', [
            'status' => $report['status'] ?? null,
            'config_hash' => $report['config_hash'] ?? null,
            'finished_at' => $report['finished_at'] ?? null,
            'errors' => $report['errors'] ?? [],
        ]);
    }

    /**
     * @param \SimpleXMLElement $config
     */
    private function localNatCount($config): int
    {
        $count = 0;
        if (isset($config->nat->rule)) {
            $count += count($config->nat->rule);
        }
        if (isset($config->nat->outbound->rule)) {
            $count += count($config->nat->outbound->rule);
        }
        if (isset($config->nat->onetoone->rule)) {
            $count += count($config->nat->onetoone->rule);
        }
        return $count;
    }

    /**
     * @param \SimpleXMLElement $config
     * @return list<string>
     */
    private function localInterfaceNames($config): array
    {
        $names = [];
        if (isset($config->interfaces)) {
            foreach ($config->interfaces->children() as $key => $interface) {
                $names[] = (string)$key;
            }
        }
        return $names;
    }

    /**
     * @param \SimpleXMLElement $config
     */
    private function localRouteCount($config): int
    {
        return isset($config->staticroutes->route) ? count($config->staticroutes->route) : 0;
    }

    /**
     * @param \SimpleXMLElement $config
     */
    private function localVlanCount($config): int
    {
        return isset($config->vlans->vlan) ? count($config->vlans->vlan) : 0;
    }

    /**
     * @param \SimpleXMLElement $config
     */
    private function localVpnCount($config): int
    {
        $count = 0;
        if (isset($config->ipsec->phase1)) {
            $count += count($config->ipsec->phase1);
        }
        if (isset($config->openvpn->openvpn-server)) {
            $count += count($config->openvpn->openvpn-server);
        }
        if (isset($config->openvpn->openvpn-client)) {
            $count += count($config->openvpn->openvpn-client);
        }
        if (isset($config->installedpackages->wireguard->server->servers)) {
            $count += count($config->installedpackages->wireguard->server->servers);
        }
        return $count;
    }
}
