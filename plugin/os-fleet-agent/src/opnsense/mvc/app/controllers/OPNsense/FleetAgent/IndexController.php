<?php

namespace OPNsense\FleetAgent;

/**
 * OFME Fleet Agent configuration and status page.
 */
class IndexController extends \OPNsense\Base\IndexController
{
    public function indexAction()
    {
        $this->view->pick('OPNsense/FleetAgent/index');
        $this->view->generalForm = $this->getForm('general');
    }
}
