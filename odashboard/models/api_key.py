import hashlib
import logging
import secrets
from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class OdashboardApiKey(models.Model):
    _name = 'odashboard.api.key'
    _description = "O'Dashboard API Key"

    _sql_constraints = [
        ('key_hash_unique', 'unique(key_hash)', 'The API key must be unique!'),
    ]

    name = fields.Char(string='Name', required=True)
    # The raw key is stored temporarily at creation for display only.
    # After creation, the field is cleared and only the hash is kept.
    key = fields.Char(string='API Key (raw)', copy=False)
    # SHA-256 hash of the key — used for authentication lookups
    key_hash = fields.Char(string='Key Hash', copy=False, index=True)
    active = fields.Boolean(string='Active', default=True)
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user, ondelete='set null')

    # Key type: default (managed by ODashboard) or custom (managed by admin)
    key_type = fields.Selection([
        ('default', "Default (managed by O'Dashboard)"),
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

    @staticmethod
    def _hash_key(raw_key):
        """Compute SHA-256 hash of an API key for secure storage."""
        return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()

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
        # Migrate existing plaintext keys to hashed storage.
        # Any record with a key but no key_hash gets its hash computed.
        self.env.cr.execute("""
            SELECT id, key FROM odashboard_api_key
            WHERE key IS NOT NULL AND key != '' AND (key_hash IS NULL OR key_hash = '')
        """)
        rows = self.env.cr.fetchall()
        for key_id, raw_key in rows:
            key_hash = self._hash_key(raw_key)
            self.env.cr.execute(
                "UPDATE odashboard_api_key SET key_hash = %s, key = NULL WHERE id = %s",
                [key_hash, key_id]
            )
        if rows:
            _logger.info("Migrated %d API key(s) to hashed storage (plaintext cleared)", len(rows))
        # Drop old unique constraint on 'key' column if it exists
        self.env.cr.execute("""
            DO $$ BEGIN
                ALTER TABLE odashboard_api_key DROP CONSTRAINT IF EXISTS odashboard_api_key_key_unique;
            EXCEPTION WHEN undefined_object THEN NULL;
            END $$;
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
            # Compute hash from the raw key
            vals['key_hash'] = self._hash_key(vals['key'])
        records = super().create(vals_list)
        # Clear raw key for default keys after creation (only hash is kept)
        for record in records:
            if record.key_type == 'default':
                super(OdashboardApiKey, record).write({'key': False})
        return records

    def write(self, vals):
        """Prevent modification of default keys (except by sudo)."""
        if not self.env.su and any(rec.key_type == 'default' for rec in self):
            # Allow only specific fields to be updated for default keys
            allowed_fields = {'last_used', 'usage_count', 'active'}
            if not set(vals.keys()).issubset(allowed_fields):
                raise ValidationError(
                    "Default API keys are managed by O'Dashboard and cannot be modified."
                )
        # If key is being updated, recompute hash
        if 'key' in vals and vals['key']:
            vals['key_hash'] = self._hash_key(vals['key'])
        return super().write(vals)

    def unlink(self):
        """Prevent deletion of default keys (except by sudo)."""
        if not self.env.su and any(rec.key_type == 'default' for rec in self):
            raise ValidationError(
                "Default API keys are managed by O'Dashboard and cannot be deleted."
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
                "Default API keys are managed by O'Dashboard and cannot be regenerated manually."
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
                'name': "O'Dashboard Default Key",
                'key_type': 'default',
                'user_id': False,  # No specific user
            })

        return default_key

    @api.model
    def rotate_default_key(self):
        """Rotate the default key and return the new key value.

        Called by ODashboard during sync. Creates the key if it doesn't exist.
        Returns the new API key string (plaintext). The hash is stored in DB.
        """
        default_key = self.get_or_create_default_key()
        new_key = self._generate_api_key()
        # Write key + hash (key is cleared after for default keys)
        default_key.sudo().write({'key': new_key})
        # Clear raw key — only hash remains in DB
        super(OdashboardApiKey, default_key.sudo()).write({'key': False})
        return new_key

    @api.model
    def authenticate_by_key(self, raw_key):
        """Look up an API key by its hash for authentication.
        
        Returns the key record if found and active, otherwise False.
        This is constant-time safe at the application level (hash comparison).
        """
        key_hash = self._hash_key(raw_key)
        return self.sudo().search([
            ('key_hash', '=', key_hash),
            ('active', '=', True),
        ], limit=1)
