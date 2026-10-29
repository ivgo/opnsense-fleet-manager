{#
 # OFME Fleet Agent configuration and status page.
 #}

<script>
    $(document).ready(function () {
        function esc(value) {
            if (value === null || value === undefined) {
                return '';
            }
            return String(value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        function showMessage(kind, message) {
            var $box = $('#ofme-message');
            $box.removeClass('hidden alert-success alert-warning alert-danger alert-info');
            $box.addClass('alert-' + kind).text(message);
        }

        function setText(id, value) {
            $('#' + id).text(value === null || value === undefined || value === '' ? '-' : value);
        }

        function badge(enabled, onText, offText) {
            return enabled
                ? '<span class="label label-success">' + esc(onText) + '</span>'
                : '<span class="label label-default">' + esc(offText) + '</span>';
        }

        function loadStatus() {
            ajaxCall('/api/fleetagent/settings/status', {}, function (data) {
                if (!data || data.status === 'error') {
                    showMessage('danger', (data && data.message) ? data.message : 'Unable to read the agent status.');
                    return;
                }

                $('#st_service').html(badge(data.service_running, 'running', 'stopped'));
                $('#st_enabled').html(badge(data.enabled, 'enabled', 'disabled'));
                $('#st_enrolled').html(badge(data.enrolled, 'enrolled', 'not enrolled'));
                setText('st_device_id', data.device_id);
                setText('st_device_name', data.device_name);
                setText('st_platform', data.platform_url);
                setText('st_heartbeat', data.heartbeat_interval ? data.heartbeat_interval + ' s' : '');
                setText('st_config_interval', data.config_interval ? data.config_interval + ' s' : '');
                setText('st_last_seen', data.last_seen);
                setText('st_last_hash', data.last_desired_hash || data.last_config_hash);
                setText('st_connectivity', data.consecutive_failures > 0 ? data.consecutive_failures + ' consecutive failures' : 'ok');

                var cert = data.certificate;
                if (cert) {
                    setText('st_cert_cn', cert.subject_cn);
                    setText('st_cert_serial', cert.serial);
                    setText('st_cert_valid_to', cert.valid_to_iso + ' (' + cert.days_left + ' days)');
                    setText('st_cert_issuer', cert.issuer_cn);
                    $('#st_cert_expired').html(badge(!cert.expired, 'valid', 'expired'));
                } else {
                    setText('st_cert_cn', '');
                    setText('st_cert_serial', '');
                    setText('st_cert_valid_to', '');
                    setText('st_cert_issuer', '');
                    $('#st_cert_expired').html(badge(false, 'valid', 'missing'));
                }

                var error = data.last_error;
                if (error) {
                    $('#st_error_row').removeClass('hidden');
                    setText('st_last_error', error);
                } else {
                    $('#st_error_row').addClass('hidden');
                }

                setText('st_pending_commands', data.pending_command_results);
                var apply = data.last_apply;
                if (apply) {
                    setText('st_last_apply', (apply.status || 'unknown') + ' at ' + (apply.finished_at || '-'));
                } else {
                    setText('st_last_apply', '');
                }

                $('#ofme-version').text(data.agent_version || '');
            }, 'GET');
        }

        function loadLog() {
            ajaxCall('/api/fleetagent/agent/log', { lines: 200 }, function (data) {
                var rows = (data && data.lines) ? data.lines : [];
                var html = '';
                for (var i = rows.length - 1; i >= 0; i--) {
                    var row = rows[i] || {};
                    var level = String(row.level || 'info');
                    var cls = level === 'error' ? 'danger' : (level === 'warning' ? 'warning' : '');
                    html += '<tr class="' + cls + '">'
                        + '<td class="text-nowrap">' + esc(row.ts) + '</td>'
                        + '<td>' + esc(level) + '</td>'
                        + '<td><code>' + esc(row.message) + '</code>'
                        + (row.context && Object.keys(row.context).length
                            ? '<br><small>' + esc(JSON.stringify(row.context)) + '</small>'
                            : '')
                        + '</td></tr>';
                }
                if (html === '') {
                    html = '<tr><td colspan="3" class="text-muted">No log entries.</td></tr>';
                }
                $('#log_body').html(html);
            }, 'GET');
        }

        function postAction(endpoint, payload, button, successText) {
            var $button = $(button);
            $button.prop('disabled', true);
            ajaxCall(endpoint, payload || {}, function (data) {
                $button.prop('disabled', false);
                if (!data || data.status === 'error') {
                    showMessage('danger', (data && data.message) ? data.message : 'The operation failed.');
                } else {
                    showMessage('success', successText);
                }
                loadStatus();
                loadLog();
            }, 'POST');
        }

        function confirmDialog(title, message, callback) {
            BootstrapDialog.show({
                type: BootstrapDialog.TYPE_WARNING,
                title: title,
                message: message,
                buttons: [
                    {
                        label: 'Cancel',
                        action: function (dialog) {
                            dialog.close();
                        }
                    },
                    {
                        label: 'Continue',
                        cssClass: 'btn-primary',
                        action: function (dialog) {
                            dialog.close();
                            callback();
                        }
                    }
                ]
            });
        }

        mapDataToFormUI({ frm_GeneralSettings: '/api/fleetagent/settings/get' });

        $('#saveAct').on('click', function () {
            saveFormToEndpoint('/api/fleetagent/settings/set', 'frm_GeneralSettings', function () {
                showMessage('success', 'Settings saved.');
                loadStatus();
            });
        });

        $('#refreshAct').on('click', function () {
            loadStatus();
            loadLog();
        });

        $('#testAct').on('click', function () {
            postAction('/api/fleetagent/agent/test', {}, '#testAct', 'The platform is reachable.');
        });

        $('#enrollAct').on('click', function () {
            confirmDialog('Enroll firewall', 'Enroll this firewall with the configured platform? The enrollment token from the settings form is used.', function () {
                postAction('/api/fleetagent/agent/enroll', {}, '#enrollAct', 'Enrollment completed.');
            });
        });

        $('#renewAct').on('click', function () {
            confirmDialog('Renew certificate', 'Request a renewed device certificate from the platform?', function () {
                postAction('/api/fleetagent/agent/renew', {}, '#renewAct', 'Certificate renewed.');
            });
        });

        $('#previewAct').on('click', function () {
            var $button = $(this);
            $button.prop('disabled', true);
            ajaxCall('/api/fleetagent/agent/preview', {}, function (data) {
                $button.prop('disabled', false);
                if (!data || data.status === 'error') {
                    showMessage('danger', (data && data.message) ? data.message : 'Unable to build the preview.');
                    return;
                }
                var summary = 'Hash: ' + (data.config_hash || '-') + '\n'
                    + 'Aliases: ' + JSON.stringify(data.aliases || {}) + '\n'
                    + 'Firewall rules: ' + JSON.stringify(data.firewall_rules || {}) + '\n'
                    + 'Drift: ' + JSON.stringify(data.drift || []);
                BootstrapDialog.show({
                    title: 'Configuration preview',
                    message: $('<pre></pre>').text(summary),
                    size: BootstrapDialog.SIZE_WIDE
                });
            }, 'GET');
        });

        $('#syncAct').on('click', function () {
            confirmDialog('Synchronise configuration', 'Apply the desired aliases and firewall rules now? Review the preview first.', function () {
                postAction('/api/fleetagent/agent/sync', {}, '#syncAct', 'Configuration synchronised.');
            });
        });

        $('#diagnosticsAct').on('click', function () {
            var $button = $(this);
            $button.prop('disabled', true);
            ajaxCall('/api/fleetagent/agent/diagnostics', {}, function (data) {
                $button.prop('disabled', false);
                if (!data || data.status === 'error') {
                    showMessage('danger', (data && data.message) ? data.message : 'Unable to collect diagnostics.');
                    return;
                }
                showMessage('success', 'Diagnostics written to ' + (data.path || 'the configuration directory') + '.');
            }, 'GET');
        });

        $('#restartAct').on('click', function () {
            confirmDialog('Restart agent', 'Restart the OFME Fleet Agent service?', function () {
                postAction('/api/fleetagent/agent/service', { command: 'restart' }, '#restartAct', 'Service restarted.');
            });
        });

        $('#startAct').on('click', function () {
            postAction('/api/fleetagent/agent/service', { command: 'start' }, '#startAct', 'Service started.');
        });

        $('#stopAct').on('click', function () {
            confirmDialog('Stop agent', 'Stop the OFME Fleet Agent service?', function () {
                postAction('/api/fleetagent/agent/service', { command: 'stop' }, '#stopAct', 'Service stopped.');
            });
        });

        $('#resetAct').on('click', function () {
            BootstrapDialog.show({
                type: BootstrapDialog.TYPE_DANGER,
                title: 'Reset enrollment',
                message: 'This removes the device certificate, private key, CA and local state. The firewall will stop reporting until it is enrolled again. Continue?',
                buttons: [
                    {
                        label: 'Cancel',
                        action: function (dialog) {
                            dialog.close();
                        }
                    },
                    {
                        label: 'Reset enrollment',
                        cssClass: 'btn-danger',
                        action: function (dialog) {
                            dialog.close();
                            postAction('/api/fleetagent/agent/reset', { confirm: 'yes' }, '#resetAct', 'Enrollment was reset.');
                        }
                    }
                ]
            });
        });

        $('#importCaAct').on('click', function () {
            var pem = $('#import_ca_pem').val();
            if (!pem) {
                showMessage('warning', 'Paste a PEM certificate first.');
                return;
            }
            var $button = $(this);
            $button.prop('disabled', true);
            ajaxCall('/api/fleetagent/settings/importCA', { pem: pem }, function (data) {
                $button.prop('disabled', false);
                if (!data || data.status === 'error') {
                    showMessage('danger', (data && data.message) ? data.message : 'The CA could not be imported.');
                    return;
                }
                $('#import_ca_pem').val('');
                showMessage('success', 'CA imported. Fingerprint: ' + (data.ca_fingerprint || 'unknown'));
                loadStatus();
            }, 'POST');
        });

        loadStatus();
        loadLog();
        window.setInterval(loadStatus, 30000);
    });
</script>

<div class="alert hidden" id="ofme-message" role="alert"></div>

<div class="row">
    <div class="col-md-6">
        <div class="panel panel-default">
            <div class="panel-heading">
                <h3 class="panel-title">{{ lang._('Agent status') }}</h3>
            </div>
            <div class="panel-body">
                <table class="table table-condensed">
                    <tbody>
                        <tr><th style="width: 38%;">{{ lang._('Service') }}</th><td id="st_service">-</td></tr>
                        <tr><th>{{ lang._('Configuration') }}</th><td id="st_enabled">-</td></tr>
                        <tr><th>{{ lang._('Enrollment') }}</th><td id="st_enrolled">-</td></tr>
                        <tr><th>{{ lang._('Device ID') }}</th><td id="st_device_id">-</td></tr>
                        <tr><th>{{ lang._('Device name') }}</th><td id="st_device_name">-</td></tr>
                        <tr><th>{{ lang._('Platform') }}</th><td id="st_platform">-</td></tr>
                        <tr><th>{{ lang._('Heartbeat interval') }}</th><td id="st_heartbeat">-</td></tr>
                        <tr><th>{{ lang._('Config interval') }}</th><td id="st_config_interval">-</td></tr>
                        <tr><th>{{ lang._('Last seen') }}</th><td id="st_last_seen">-</td></tr>
                        <tr><th>{{ lang._('Last applied hash') }}</th><td id="st_last_hash">-</td></tr>
                        <tr><th>{{ lang._('Last apply') }}</th><td id="st_last_apply">-</td></tr>
                        <tr><th>{{ lang._('Connectivity') }}</th><td id="st_connectivity">-</td></tr>
                        <tr><th>{{ lang._('Pending command results') }}</th><td id="st_pending_commands">-</td></tr>
                        <tr id="st_error_row" class="danger hidden"><th>{{ lang._('Last error') }}</th><td id="st_last_error"></td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    <div class="col-md-6">
        <div class="panel panel-default">
            <div class="panel-heading">
                <h3 class="panel-title">{{ lang._('Device certificate') }}</h3>
            </div>
            <div class="panel-body">
                <table class="table table-condensed">
                    <tbody>
                        <tr><th style="width: 38%;">{{ lang._('State') }}</th><td id="st_cert_expired">-</td></tr>
                        <tr><th>{{ lang._('Common name') }}</th><td id="st_cert_cn">-</td></tr>
                        <tr><th>{{ lang._('Serial') }}</th><td id="st_cert_serial" style="word-break: break-all;">-</td></tr>
                        <tr><th>{{ lang._('Valid until') }}</th><td id="st_cert_valid_to">-</td></tr>
                        <tr><th>{{ lang._('Issuer') }}</th><td id="st_cert_issuer">-</td></tr>
                        <tr><th>{{ lang._('Agent version') }}</th><td id="ofme-version">-</td></tr>
                    </tbody>
                </table>
                <p class="text-muted">
                    {{ lang._('The agent connects outbound only. No inbound management port is opened on this firewall.') }}
                </p>
            </div>
        </div>
    </div>
</div>

<div class="panel panel-default">
    <div class="panel-heading">
        <h3 class="panel-title">{{ lang._('Operations') }}</h3>
    </div>
    <div class="panel-body">
        <div class="btn-group" role="group">
            <button type="button" class="btn btn-default" id="refreshAct"><span class="fa fa-refresh"></span> {{ lang._('Refresh') }}</button>
            <button type="button" class="btn btn-default" id="testAct"><span class="fa fa-plug"></span> {{ lang._('Test connection') }}</button>
            <button type="button" class="btn btn-primary" id="enrollAct"><span class="fa fa-certificate"></span> {{ lang._('Enroll') }}</button>
            <button type="button" class="btn btn-default" id="renewAct"><span class="fa fa-refresh"></span> {{ lang._('Renew certificate') }}</button>
        </div>
        <div class="btn-group" role="group">
            <button type="button" class="btn btn-default" id="previewAct"><span class="fa fa-search"></span> {{ lang._('Preview policy') }}</button>
            <button type="button" class="btn btn-warning" id="syncAct"><span class="fa fa-cloud-download"></span> {{ lang._('Synchronise now') }}</button>
            <button type="button" class="btn btn-default" id="diagnosticsAct"><span class="fa fa-stethoscope"></span> {{ lang._('Diagnostics') }}</button>
        </div>
        <div class="btn-group" role="group">
            <button type="button" class="btn btn-success" id="startAct"><span class="fa fa-play"></span> {{ lang._('Start') }}</button>
            <button type="button" class="btn btn-default" id="restartAct"><span class="fa fa-repeat"></span> {{ lang._('Restart') }}</button>
            <button type="button" class="btn btn-default" id="stopAct"><span class="fa fa-stop"></span> {{ lang._('Stop') }}</button>
            <button type="button" class="btn btn-danger" id="resetAct"><span class="fa fa-trash"></span> {{ lang._('Reset enrollment') }}</button>
        </div>
    </div>
</div>

<div class="row">
    <div class="col-md-7">
        <div class="panel panel-default">
            <div class="panel-heading">
                <h3 class="panel-title">{{ lang._('Settings') }}</h3>
            </div>
            <div class="panel-body">
                {{ partial("layout_partials/base_form", ['fields': generalForm, 'id': 'frm_GeneralSettings']) }}
            </div>
        </div>
    </div>
    <div class="col-md-5">
        <div class="panel panel-default">
            <div class="panel-heading">
                <h3 class="panel-title">{{ lang._('Platform CA pinning') }}</h3>
            </div>
            <div class="panel-body">
                <p class="text-muted">
                    {{ lang._('Enrollment and renewal install the platform CA automatically. Paste a PEM certificate here only when the trust anchor must be pinned before the first connection, for example when TLS verification is temporarily disabled during bootstrap.') }}
                </p>
                <textarea id="import_ca_pem" class="form-control" rows="8" placeholder="-----BEGIN CERTIFICATE-----"></textarea>
                <br/>
                <button type="button" class="btn btn-primary" id="importCaAct">
                    <span class="fa fa-key"></span> {{ lang._('Import CA') }}
                </button>
            </div>
        </div>
    </div>
</div>

<div class="panel panel-default">
    <div class="panel-heading">
        <h3 class="panel-title">{{ lang._('Recent agent log') }}</h3>
    </div>
    <div class="panel-body">
        <div class="table-responsive" style="max-height: 420px; overflow-y: auto;">
            <table class="table table-condensed table-striped">
                <thead>
                    <tr>
                        <th style="width: 18%;">{{ lang._('Time') }}</th>
                        <th style="width: 10%;">{{ lang._('Level') }}</th>
                        <th>{{ lang._('Message') }}</th>
                    </tr>
                </thead>
                <tbody id="log_body">
                    <tr><td colspan="3" class="text-muted">{{ lang._('Loading...') }}</td></tr>
                </tbody>
            </table>
        </div>
    </div>
</div>

<div class="col-md-12">
    <button class="btn btn-primary" id="saveAct" type="button">
        <b>{{ lang._('Save settings') }}</b>
    </button>
</div>
