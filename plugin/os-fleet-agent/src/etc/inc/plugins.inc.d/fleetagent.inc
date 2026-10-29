<?php

/**
 * OPNsense service registration for the OFME Fleet Agent.
 */

function os_fleet_agent_enabled()
{
    $model = new \OPNsense\FleetAgent\Settings();
    return (string)$model->enabled === '1';
}

function os_fleet_agent_services()
{
    if (!os_fleet_agent_enabled()) {
        return [];
    }

    return [
        [
            'description' => gettext('OFME Fleet Agent'),
            'configd' => [
                'restart' => ['ofme restart'],
                'start' => ['ofme start'],
                'stop' => ['ofme stop'],
            ],
            'name' => 'os_fleet_agent',
        ],
    ];
}
