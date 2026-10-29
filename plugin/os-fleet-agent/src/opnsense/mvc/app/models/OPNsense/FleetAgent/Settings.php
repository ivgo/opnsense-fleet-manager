<?php

namespace OPNsense\FleetAgent;

/**
 * OFME Fleet Agent settings model.
 *
 * The mount point (//OPNsense/fleetagent) is declared in Settings.xml and is
 * resolved by the OPNsense model framework. Certificate material is never
 * stored here; it lives in /usr/local/etc/ofme-agent with 0600 permissions.
 */
class Settings extends \OPNsense\Base\FieldTypes\BaseModel
{
}
