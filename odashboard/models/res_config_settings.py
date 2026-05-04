import requests

from odoo import api, fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ODashboard configuration
    odashboard_api_url = fields.Char(
        string="O'Dashboard API URL",
        config_parameter='odashboard.api_url',
        default='https://api.odashboard.app',
        help="The O'Dashboard API server URL (e.g. https://api.odashboard.app)",
    )
    odashboard_frontend_url = fields.Char(
        string="O'Dashboard App URL",
        config_parameter='odashboard.frontend_url',
        default='https://odashboard.app',
        help="The O'Dashboard web application URL (e.g. https://odashboard.app)",
    )
    odashboard_instance_key = fields.Char(
        string='Instance Key',
        config_parameter='odashboard.instance_key',
        help="The O'Dashboard instance key. Copy it from your instance settings.",
    )
    odashboard_sync_status = fields.Selection(
        selection=[
            ('not_configured', 'Not Configured'),
            ('pending', 'Pending'),
            ('connected', 'Connected'),
        ],
        string='Connection Status',
        compute='_compute_odashboard_sync_status',
        help="Current connection status with O'Dashboard",
    )

    @api.depends('odashboard_api_url', 'odashboard_instance_key')
    def _compute_odashboard_sync_status(self):
        """Compute the sync status from real stored state.

        The flag ``odashboard.connected`` is persisted in ``ir.config_parameter``
        and is set to ``'true'`` **only** after a successful sync.  It is reset
        whenever the instance key changes.

        Duplicated-database detection:
        When a sync succeeds, we store ``web.base.url`` as
        ``odashboard.synced_odoo_url``.  If, on a later compute, the current
        ``web.base.url`` no longer matches, this database has been duplicated
        (e.g. staging copied from prod).  We automatically invalidate the
        connection to prevent the staging from acting as the prod instance.

        Status logic:
        - not_configured: Missing API URL or instance key
        - pending: Configured but not yet connected (sync needed)
        - connected: Sync succeeded (odashboard.connected == 'true')
        """
        ICP = self.env['ir.config_parameter'].sudo()
        is_connected = ICP.get_param('odashboard.connected', default='') == 'true'

        # Detect duplicated database: if the URL changed since last sync,
        # this is likely a staging copy — auto-invalidate the connection.
        if is_connected:
            synced_url = ICP.get_param('odashboard.synced_odoo_url', default='')
            current_url = ICP.get_param('web.base.url', default='')
            if synced_url and current_url and synced_url != current_url:
                ICP.set_param('odashboard.connected', '')
                is_connected = False
                # Note: we do NOT delete API keys or instance_key here.
                # The admin must explicitly disconnect or reconfigure.

        for record in self:
            if not record.odashboard_api_url or not record.odashboard_instance_key:
                record.odashboard_sync_status = 'not_configured'
            elif is_connected:
                record.odashboard_sync_status = 'connected'
            else:
                record.odashboard_sync_status = 'pending'

    def set_values(self):
        """Override to detect instance_key changes and invalidate the connection."""
        ICP = self.env['ir.config_parameter'].sudo()
        old_key = ICP.get_param('odashboard.instance_key', default='')
        new_key = self.odashboard_instance_key or ''

        res = super().set_values()

        # If instance_key changed (new value or cleared), the old default API key
        # is no longer valid — delete it and reset the connected flag.
        if new_key != old_key:
            ICP.set_param('odashboard.connected', '')
            ICP.set_param('odashboard.instance_identifier', '')
            ICP.set_param('odashboard.synced_odoo_url', '')

            ApiKey = self.env['odashboard.api.key'].sudo()
            default_keys = ApiKey.search([('key_type', '=', 'default')])
            if default_keys:
                default_keys.unlink()

        return res

    def action_odashboard_sync(self):
        """Trigger synchronization with ODashboard.

        Reads values from the transient record (self) directly so that
        unsaved form values are honored. Persists them via set_values()
        so the ir.config_parameter table is up to date for later use.
        """
        self.ensure_one()

        # Read values from the form (may include unsaved changes)
        api_url = (self.odashboard_api_url or '').strip()
        instance_key = (self.odashboard_instance_key or '').strip()

        if not api_url:
            raise UserError("Please configure the O'Dashboard API URL first.")
        if not instance_key:
            raise UserError('Please configure the instance key first.')

        # Persist the current form values to ir.config_parameter so that
        # subsequent reads (e.g. in other methods or requests) see them.
        self.set_values()

        ICP = self.env['ir.config_parameter'].sudo()

        # Normalize URLs
        api_url = api_url.rstrip('/')
        odoo_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')

        if not odoo_url:
            raise UserError('Unable to determine the Odoo base URL.')

        if not odoo_url.startswith('https://'):
            raise UserError(
                "Your Odoo base URL must use HTTPS for O'Dashboard synchronization to work.\n\n"
                f"Current URL: {odoo_url}\n\n"
                "Please update your web.base.url in Settings → Technical → System Parameters "
                "to use https:// (e.g. https://yourdomain.com)."
            )

        # Include instance_identifier if we have one from a previous sync.
        # This allows the backend to detect duplicated databases (e.g. staging
        # copied from prod) that inherited the same instance_key.
        instance_identifier = ICP.get_param('odashboard.instance_identifier', default='')

        sync_payload = {'odoo_url': odoo_url}
        if instance_identifier:
            sync_payload['instance_identifier'] = instance_identifier

        try:
            # Call ODashboard sync endpoint
            response = requests.post(
                f'{api_url}/instances/sync',
                json=sync_payload,
                headers={
                    'X-Instance-Key': instance_key,
                    'Content-Type': 'application/json',
                },
                timeout=60,
            )

            if response.status_code == 401:
                raise UserError('Invalid instance key. Please check your configuration.')
            elif response.status_code == 409:
                # Conflict — another Odoo is already connected, or this is a
                # duplicated database (staging). Clear local connection state
                # to prevent further accidental syncs.
                ICP.set_param('odashboard.connected', '')
                data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                raise UserError(
                    data.get('detail',
                             "This O'Dashboard instance is already connected to another Odoo database. "
                             'Please disconnect the other database before syncing.')
                )
            elif response.status_code == 502:
                # ODashboard tried to call us but failed — likely a network issue
                data = response.json()
                raise UserError(f"O'Dashboard could not reconnect to Odoo: {data.get('detail', 'Unknown error')}")
            elif response.status_code != 200:
                data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                raise UserError(f'Synchronization failed: {data.get("detail", response.text)}')

            # Store instance_identifier (public UUID) returned by the API.
            # This is used in iframe tokens to identify the instance without
            # exposing the secret instance_key.
            sync_data = response.json()
            instance_identifier = sync_data.get('instance_identifier', '')
            if instance_identifier:
                ICP.set_param('odashboard.instance_identifier', instance_identifier)

            # Mark as connected — this is the ONLY place this flag gets set.
            ICP.set_param('odashboard.connected', 'true')

            # Store the current Odoo URL at sync time. Used to detect
            # duplicated databases (staging) on subsequent settings loads.
            ICP.set_param('odashboard.synced_odoo_url', odoo_url)

            # Success — reload the settings form to update the badge
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Synchronization Successful',
                    'message': "The connection with O'Dashboard has been established. Users and schema have been synchronized.",
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.client',
                        'tag': 'reload',
                    },
                }
            }

        except requests.exceptions.Timeout:
            raise UserError("The connection to O'Dashboard timed out. Please try again.")
        except requests.exceptions.ConnectionError:
            raise UserError(f"Unable to connect to O'Dashboard ({api_url}). Please check the URL.")
        except requests.exceptions.RequestException as e:
            raise UserError(f'Connection error: {str(e)}')

    def action_odashboard_disconnect(self):
        """Disconnect from ODashboard.

        Calls the ODashboard backend to clear the odoo_url (desync), then
        cleans up local state. Only proceeds with local cleanup if the
        backend confirms the desync (or if the instance was never synced).
        """
        self.ensure_one()

        ICP = self.env['ir.config_parameter'].sudo()
        api_url = (ICP.get_param('odashboard.api_url', default='') or '').rstrip('/')
        instance_key = ICP.get_param('odashboard.instance_key', default='')
        is_connected = ICP.get_param('odashboard.connected', default='') == 'true'

        # If we have a backend connection, notify it to clear odoo_url
        if api_url and instance_key and is_connected:
            try:
                response = requests.post(
                    f'{api_url}/instances/desync',
                    headers={
                        'X-Instance-Key': instance_key,
                        'Content-Type': 'application/json',
                    },
                    timeout=15,
                )
                if response.status_code not in (204, 401):
                    # Unexpected error — abort disconnect
                    data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                    raise UserError(
                        f"Unable to disconnect on O'Dashboard side: {data.get('detail', response.text)}. "
                        'Please try again or contact support.'
                    )
                # 204 = success, 401 = key already invalid (fine to proceed)
            except requests.exceptions.Timeout:
                raise UserError(
                    "The connection to O'Dashboard timed out. "
                    'Please try again.'
                )
            except requests.exceptions.ConnectionError:
                raise UserError(
                    f"Unable to connect to O'Dashboard ({api_url}). "
                    'Please check your network connection and try again.'
                )

        # Backend confirmed (or was never connected) — clean up local state
        ICP.set_param('odashboard.instance_key', '')
        ICP.set_param('odashboard.instance_identifier', '')
        ICP.set_param('odashboard.synced_odoo_url', '')
        ICP.set_param('odashboard.connected', '')

        # Delete all default API keys
        ApiKey = self.env['odashboard.api.key'].sudo()
        default_keys = ApiKey.search([('key_type', '=', 'default')])
        if default_keys:
            default_keys.unlink()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "O'Dashboard Disconnected",
                'message': "The connection with O'Dashboard has been removed on both sides.",
                'type': 'warning',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            }
        }
