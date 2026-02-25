import secrets
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class OdashboardApiKey(models.Model):
    _name = 'odashboard.api.key'
    _description = 'ODashboard API Key'

    _sql_constraints = [
        ('key_unique', 'unique(key)', 'The API key must be unique!'),
    ]

    name = fields.Char(string='Name', required=True)
    key = fields.Char(string='API Key', copy=False)
    active = fields.Boolean(string='Active', default=True)
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user, ondelete='set null')

    # Key type: default (managed by ODashboard) or custom (managed by admin)
    key_type = fields.Selection([
        ('default', 'Default (managed by ODashboard)'),
        ('custom', 'Custom'),
    ], string='Type', default='custom', required=True)

    # Access control (only for custom keys)
    allowed_models = fields.Char(
        string='Allowed Models',
        help='Comma-separated list of model names. Leave empty to allow all models.'
    )

    # Audit
    last_used = fields.Datetime(string='Last Used', readonly=True)
    usage_count = fields.Integer(string='Usage Count', default=0, readonly=True)

    # Computed field to hide key value for default type
    key_display = fields.Char(
        string='API Key',
        compute='_compute_key_display',
        help='The API key value. Hidden for default keys.'
    )

    @api.constrains('key_type', 'active')
    def _check_unique_default(self):
        """Ensure only one active default key exists."""
        for record in self:
            if record.key_type == 'default' and record.active:
                existing = self.search([
                    ('key_type', '=', 'default'),
                    ('active', '=', True),
                    ('id', '!=', record.id),
                ])
                if existing:
                    raise ValidationError('Only one active default API key is allowed.')

    def init(self):
        """Create partial unique index to enforce single active default key at DB level."""
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS odashboard_api_key_unique_active_default
            ON odashboard_api_key (key_type)
            WHERE key_type = 'default' AND active = true
        """)

    @api.depends('key', 'key_type')
    def _compute_key_display(self):
        """Show key for custom type, hide for default type."""
        for record in self:
            if record.key_type == 'default':
                record.key_display = '••••••••••••••••••••••••••••••••'
            else:
                record.key_display = record.key or ''

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('key'):
                vals['key'] = self._generate_api_key()
        return super().create(vals_list)

    def write(self, vals):
        """Prevent modification of default keys (except by sudo)."""
        if not self.env.su and any(rec.key_type == 'default' for rec in self):
            # Allow only specific fields to be updated for default keys
            allowed_fields = {'last_used', 'usage_count', 'active'}
            if not set(vals.keys()).issubset(allowed_fields):
                raise ValidationError(
                    'Default API keys are managed by ODashboard and cannot be modified.'
                )
        return super().write(vals)

    def unlink(self):
        """Prevent deletion of default keys (except by sudo)."""
        if not self.env.su and any(rec.key_type == 'default' for rec in self):
            raise ValidationError(
                'Default API keys are managed by ODashboard and cannot be deleted.'
            )
        return super().unlink()

    def _generate_api_key(self):
        """Generate a secure random API key."""
        return f"odash_{secrets.token_urlsafe(32)}"

    def regenerate_key(self):
        """Regenerate the API key (only for custom keys)."""
        self.ensure_one()
        if self.key_type == 'default':
            raise ValidationError(
                'Default API keys are managed by ODashboard and cannot be regenerated manually.'
            )
        self.key = self._generate_api_key()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'API Key Regenerated',
                'message': 'The API key has been regenerated. Please update your configuration.',
                'type': 'warning',
                'sticky': False,
            }
        }

    def _update_usage(self):
        """Update last_used timestamp and increment usage count atomically.

        Uses raw SQL to ensure atomic increment of usage_count,
        preventing race conditions under concurrent requests.
        """
        self.env.cr.execute("""
            UPDATE odashboard_api_key
            SET last_used = NOW() AT TIME ZONE 'UTC',
                usage_count = usage_count + 1
            WHERE id = %s
        """, [self.id])
        # Invalidate cache for these fields
        self.invalidate_recordset(['last_used', 'usage_count'])

    def is_model_allowed(self, model_name):
        """Check if access to a model is allowed for this API key.

        Default keys have access to all models.
        Custom keys respect the allowed_models restriction.
        """
        if self.key_type == 'default':
            return True
        if not self.allowed_models:
            return True
        allowed = [m.strip() for m in self.allowed_models.split(',')]
        return model_name in allowed

    @api.model
    def get_or_create_default_key(self):
        """Get the default key, creating it if it doesn't exist.

        Called by the sync process to ensure a default key exists.
        Returns the key record (use .key to get the actual key value).
        """
        default_key = self.sudo().search([
            ('key_type', '=', 'default'),
            ('active', '=', True),
        ], limit=1)

        if not default_key:
            default_key = self.sudo().create({
                'name': 'ODashboard Default Key',
                'key_type': 'default',
                'user_id': False,  # No specific user
            })

        return default_key

    @api.model
    def rotate_default_key(self):
        """Rotate the default key and return the new key value.

        Called by ODashboard during sync. Creates the key if it doesn't exist.
        Returns the new API key string.
        """
        default_key = self.get_or_create_default_key()
        new_key = self._generate_api_key()
        default_key.sudo().write({'key': new_key})
        return new_key
