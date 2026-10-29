<?php

/*
 * OFME Fleet Agent privileges.
 *
 * The privilege names are referenced by the ACL definitions in
 * models/OPNsense/FleetAgent/ACL/ACL.xml and by the menu entries.
 */

$priv_list['page-services-fleetagent'] = [
    'name' => gettext('WebCfg - Services: OFME Fleet Agent'),
    'descr' => gettext('Access the OFME Fleet Agent configuration and status page.'),
    'match' => ['ui/fleetagent*', 'api/fleetagent/*'],
];

$priv_list['page-services-fleetagent-actions'] = [
    'name' => gettext('WebCfg - Services: OFME Fleet Agent (operations)'),
    'descr' => gettext('Enroll, renew, synchronise, restart and reset the OFME Fleet Agent.'),
    'match' => ['api/fleetagent/agent/*', 'api/fleetagent/settings/enroll*', 'api/fleetagent/settings/renew*'],
];
