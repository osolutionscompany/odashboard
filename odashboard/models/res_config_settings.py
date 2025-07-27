from odoo import models, fields, api, _
import requests
import uuid
import logging

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    odashboard_plan = fields.Char(string='Odashboard Plan', config_parameter="odashboard.plan")
    odashboard_key = fields.Char(string="Odashboard Key", config_parameter="odashboard.key")
    odashboard_key_synchronized = fields.Boolean(string="Key Synchronized",
                                                 config_parameter="odashboard.key_synchronized", readonly=True)
    odashboard_uuid = fields.Char(string="Instance UUID", config_parameter="odashboard.uuid", readonly=True)
    odashboard_engine_version = fields.Char(string="Version actuelle du moteur", readonly=True)

    def set_values(self):
        super(ResConfigSettings, self).set_values()

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        
        uuid_param = self.env['ir.config_parameter'].sudo().get_param('odashboard.uuid')
        if not uuid_param:
            uuid_param = str(uuid.uuid4())
            self.env['ir.config_parameter'].sudo().set_param('odashboard.uuid', uuid_param)
        
        engine = self.env['odash.engine'].sudo()._get_single_record()

        res.update({
            'odashboard_uuid': uuid_param,
            'odashboard_engine_version': engine.version,
        })
        
        return res
        
    def action_check_engine_updates(self):
        """Check update for Odashboard engine"""
        engine = self.env['odash.engine'].search([], limit=1)
        if not engine:
            engine = self.env['odash.engine'].create([{
                'name': 'Dashboard Engine',
                'version': '0.0.0',
                'code': False,
                'previous_code': False,
            }])
        result = engine.check_for_updates()

        if result:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Successful update'),
                    'message': _('The Odashboard Engine has been updated to version %s') % engine.version,
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Information'),
                    'message': _('No update available. You are already using the latest version (%s)') % engine.version,
                    'type': 'info',
                    'sticky': False,
                }
            }

    def synchronize_key(self):
        """Synchronize the key with the license server"""

        self.env['ir.config_parameter'].sudo().set_param('odashboard.key_synchronized', True)

        if not self.odashboard_key:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'Please enter a key before synchronizing',
                    'type': 'danger',
                    'sticky': False,
                }
            }

        # Get the license API endpoint from config parameters
        api_endpoint = self.env['ir.config_parameter'].sudo().get_param('odashboard.api.endpoint',
                                                                        'https://odashboard.app')

        # Verify key with external platform
        try:
            response = requests.post(
                f"{api_endpoint}/api/odashboard/license/verify",
                json={
                    'key': self.odashboard_key,
                    'uuid': self.odashboard_uuid,
                    'url': self.env['ir.config_parameter'].sudo().get_param('web.base.url')
                },
            )

            if response.status_code == 200:
                result = response.json().get('result')

                if result.get('valid'):
                    if result.get('already_linked') and result.get('linked_uuid') != self.odashboard_uuid:
                        return {
                            'type': 'ir.actions.client',
                            'tag': 'display_notification',
                            'params': {
                                'title': 'Error',
                                'message': 'Key already used.',
                                'type': 'danger',
                                'sticky': False,
                            }
                        }
                    else:
                        self.env['ir.config_parameter'].sudo().set_param('odashboard.key_synchronized', True)
                        self.env["odash.dashboard"].sudo().update_auth_token()
                        return {
                            'type': 'ir.actions.act_window',
                            'res_model': 'res.config.settings',
                            'view_mode': 'form',
                            'view_type': 'form',
                            'target': 'inline',
                            'context': {'active_test': False},
                            'flags': {'form': {'action_buttons': True}},
                            'notification': {
                                'title': 'Success',
                                'message': 'Key successfully synchronized',
                                'type': 'success',
                                'sticky': False,
                            }
                        }
                else:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Error',
                            'message': result.get('error', 'Invalid key'),
                            'type': 'danger',
                            'sticky': False,
                        }
                    }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Error verifying key',
                        'type': 'danger',
                        'sticky': False,
                    }
                }
        except requests.exceptions.RequestException as e:
            _logger.error("Connection error when verifying license key: %s", str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'Connection error when verifying license key',
                    'type': 'danger',
                    'sticky': False,
                }
            }

    def desynchronize_key(self):
        """De-synchronize the key from the license server"""
        # Check if key is synchronized
        is_synchronized = bool(self.env['ir.config_parameter'].sudo().get_param('odashboard.key_synchronized', 'False'))

        if not is_synchronized:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Warning',
                    'message': 'key is not synchronized',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        key = self.env['ir.config_parameter'].sudo().get_param('odashboard.key')
        uuid_param = self.env['ir.config_parameter'].sudo().get_param('odashboard.uuid')

        # Get the license API endpoint from config parameters
        api_endpoint = self.env['ir.config_parameter'].sudo().get_param('odashboard.api.endpoint',
                                                                        'https://odashboard.app')

        # Notify the license server about desynchronization
        try:
            requests.post(
                f"{api_endpoint}/api/odashboard/license/unlink",
                json={
                    'key': key,
                    'uuid': uuid_param
                },
                timeout=10
            )

            # Regardless of the server response, we desynchronize locally
            self.env['ir.config_parameter'].sudo().set_param('odashboard.key_synchronized', False)
            self.env['ir.config_parameter'].sudo().set_param('odashboard.key', '')
            self.env['ir.config_parameter'].sudo().set_param('odashboard.plan', '')

            # Update the current record
            self.odashboard_key = ''
            self.odashboard_key_synchronized = False

            return {
                'type': 'ir.actions.act_window',
                'res_model': 'res.config.settings',
                'view_mode': 'form',
                'view_type': 'form',
                'target': 'inline',
                'context': {'active_test': False},
                'flags': {'form': {'action_buttons': True}},
                'notification': {
                    'title': 'Success',
                    'message': 'key successfully desynchronized',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            _logger.error("Error during key desynchronization: %s", str(e))
            # Even if the server request fails, we desynchronize locally
            self.env['ir.config_parameter'].sudo().set_param('odashboard.key_synchronized', False)
            self.env['ir.config_parameter'].sudo().set_param('odashboard.key', '')

            # Update the current record
            self.odashboard_key = ''
            self.odashboard_key_synchronized = False


            return {
                'type': 'ir.actions.act_window',
                'res_model': 'res.config.settings',
                'view_mode': 'form',
                'view_type': 'form',
                'target': 'inline',
                'context': {'active_test': False},
                'flags': {'form': {'action_buttons': True}},
                'notification': {
                    'title': 'Warning',
                    'message': 'Error during key desynchronization, desynchronized locally',
                    'type': 'warning',
                    'sticky': False,
                }
            }
