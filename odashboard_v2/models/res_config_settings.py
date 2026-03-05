import requests

from odoo import api, fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ODashboard configuration
    odashboard_api_url = fields.Char(
        string='URL de l\'API ODashboard',
        config_parameter='odashboard.api_url',
        help='L\'URL du serveur API ODashboard (ex : https://api.odashboard.io)',
    )
    odashboard_frontend_url = fields.Char(
        string='URL de l\'application ODashboard',
        config_parameter='odashboard.frontend_url',
        help='L\'URL de l\'application web ODashboard (ex : https://app.odashboard.io)',
    )
    odashboard_instance_key = fields.Char(
        string='Clé d\'instance',
        config_parameter='odashboard.instance_key',
        help='La clé d\'instance ODashboard. Copiez-la depuis les paramètres de votre instance.',
    )
    odashboard_sync_status = fields.Selection(
        selection=[
            ('not_configured', 'Non configuré'),
            ('pending', 'En attente'),
            ('connected', 'Connecté'),
        ],
        string='État de la connexion',
        compute='_compute_odashboard_sync_status',
        help='État actuel de la connexion avec ODashboard',
    )

    @api.depends('odashboard_api_url', 'odashboard_instance_key')
    def _compute_odashboard_sync_status(self):
        """Compute the sync status from real stored state.

        The flag ``odashboard.connected`` is persisted in ``ir.config_parameter``
        and is set to ``'true'`` **only** after a successful sync.  It is reset
        whenever the instance key changes.

        Status logic:
        - not_configured: Missing API URL or instance key
        - pending: Configured but not yet connected (sync needed)
        - connected: Sync succeeded (odashboard.connected == 'true')
        """
        ICP = self.env['ir.config_parameter'].sudo()
        is_connected = ICP.get_param('odashboard.connected', default='') == 'true'

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

            ApiKey = self.env['odashboard.api.key'].sudo()
            default_keys = ApiKey.search([('key_type', '=', 'default')])
            if default_keys:
                default_keys.unlink()

        return res

    def action_odashboard_sync(self):
        """Trigger synchronization with ODashboard."""
        self.ensure_one()

        ICP = self.env['ir.config_parameter'].sudo()
        api_url = ICP.get_param('odashboard.api_url', default='')
        instance_key = ICP.get_param('odashboard.instance_key', default='')

        if not api_url:
            raise UserError('Veuillez d\'abord configurer l\'URL de l\'API ODashboard.')
        if not instance_key:
            raise UserError('Veuillez d\'abord configurer la clé d\'instance.')

        # Normalize URLs
        api_url = api_url.rstrip('/')
        odoo_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')

        if not odoo_url:
            raise UserError('Impossible de déterminer l\'URL de base Odoo.')

        try:
            # Call ODashboard sync endpoint
            response = requests.post(
                f'{api_url}/instances/sync',
                json={'odoo_url': odoo_url},
                headers={
                    'X-Instance-Key': instance_key,
                    'Content-Type': 'application/json',
                },
                timeout=60,
            )

            if response.status_code == 401:
                raise UserError('Clé d\'instance invalide. Vérifiez votre configuration.')
            elif response.status_code == 502:
                # ODashboard tried to call us but failed — likely a network issue
                data = response.json()
                raise UserError(f'ODashboard n\'a pas pu se reconnecter à Odoo : {data.get("detail", "Erreur inconnue")}')
            elif response.status_code != 200:
                data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                raise UserError(f'Échec de la synchronisation : {data.get("detail", response.text)}')

            # Store instance_identifier (public UUID) returned by the API.
            # This is used in iframe tokens to identify the instance without
            # exposing the secret instance_key.
            sync_data = response.json()
            instance_identifier = sync_data.get('instance_identifier', '')
            if instance_identifier:
                ICP.set_param('odashboard.instance_identifier', instance_identifier)

            # Mark as connected — this is the ONLY place this flag gets set.
            ICP.set_param('odashboard.connected', 'true')

            # Success — reload the settings form to update the badge
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Synchronisation réussie',
                    'message': 'La connexion avec ODashboard a été établie. Les utilisateurs et le schéma ont été synchronisés.',
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.client',
                        'tag': 'reload',
                    },
                }
            }

        except requests.exceptions.Timeout:
            raise UserError('La connexion à ODashboard a expiré. Veuillez réessayer.')
        except requests.exceptions.ConnectionError:
            raise UserError(f'Impossible de se connecter à ODashboard ({api_url}). Vérifiez l\'URL.')
        except requests.exceptions.RequestException as e:
            raise UserError(f'Erreur de connexion : {str(e)}')

    def action_odashboard_disconnect(self):
        """Disconnect from ODashboard by clearing the instance key and deleting default API keys."""
        self.ensure_one()

        ICP = self.env['ir.config_parameter'].sudo()

        # Clear the instance key — this invalidates the connection
        ICP.set_param('odashboard.instance_key', '')

        # Clear instance identifier (received during sync)
        ICP.set_param('odashboard.instance_identifier', '')

        # Reset connection flag
        ICP.set_param('odashboard.connected', '')

        # Delete all default API keys (the key ODashboard uses to call us)
        ApiKey = self.env['odashboard.api.key'].sudo()
        default_keys = ApiKey.search([('key_type', '=', 'default')])
        if default_keys:
            default_keys.unlink()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'ODashboard déconnecté',
                'message': 'La clé d\'instance et la clé API par défaut ont été supprimées.',
                'type': 'warning',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            }
        }
