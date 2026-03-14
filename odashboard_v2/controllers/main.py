import hashlib
import hmac
import json
import logging
import re
import threading
import time

import psycopg2

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


# =============================================================================
# SIMPLE IN-MEMORY RATE LIMITER FOR API KEY AUTHENTICATION
# =============================================================================
# Tracks failed auth attempts per IP. Blocks IPs with too many failures
# to prevent brute-force attacks and DB-hitting denial-of-service.

class _AuthRateLimiter:
    """Thread-safe in-memory rate limiter for failed API key auth attempts."""

    def __init__(self, max_failures=20, window_seconds=60, block_seconds=300):
        self._lock = threading.Lock()
        self._failures = {}  # ip -> list of timestamps
        self._blocked = {}   # ip -> unblock_time
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds

    def is_blocked(self, ip):
        """Check if an IP is currently blocked."""
        with self._lock:
            unblock_time = self._blocked.get(ip)
            if unblock_time:
                if time.time() < unblock_time:
                    return True
                # Block expired
                del self._blocked[ip]
                self._failures.pop(ip, None)
            return False

    def record_failure(self, ip):
        """Record a failed auth attempt. Returns True if IP is now blocked."""
        now = time.time()
        with self._lock:
            timestamps = self._failures.get(ip, [])
            # Remove old entries outside the window
            cutoff = now - self.window_seconds
            timestamps = [t for t in timestamps if t > cutoff]
            timestamps.append(now)
            self._failures[ip] = timestamps

            if len(timestamps) >= self.max_failures:
                self._blocked[ip] = now + self.block_seconds
                _logger.warning(
                    "API key auth: IP %s blocked for %ds after %d failed attempts",
                    ip, self.block_seconds, len(timestamps),
                )
                return True
            return False

    def record_success(self, ip):
        """Clear failure count on successful auth."""
        with self._lock:
            self._failures.pop(ip, None)


_auth_limiter = _AuthRateLimiter()


class QueryExecutionError(Exception):
    """Exception raised when a SQL query fails with detailed error info."""

    def __init__(self, error_info: dict):
        self.error_info = error_info
        super().__init__(error_info.get('message', 'Query execution failed'))

# =============================================================================
# FILTERING CONFIGURATION
# =============================================================================
# Instead of excluding tables/fields, we mark them as hidden by default.
# Users can unhide them via the schema editor if needed.

# Model prefixes to hide by default (technical/system models)
HIDDEN_MODEL_PREFIXES = (
    'ir.',           # Internal models (ir.model, ir.ui.view, ir.rule, etc.)
    'base.',         # Base models (base.language.export, etc.)
    'bus.',          # Bus/notification system
    'base_import.',  # Import wizards
    'web_editor.',   # Web editor internals
    'web_tour.',     # Tour system
    'report.',       # Report engine internals
    'digest.',       # Digest emails
    'iap.',          # In-App Purchase
    'mail.resend',   # Mail resend wizards
    'fetchmail.',    # Fetchmail
    'sms.',          # SMS (unless needed)
    'phone.',        # Phone validation
    'onboarding.',   # Onboarding
    'reset.view.',   # View reset
)

# Exact model names to hide by default
HIDDEN_MODELS = {
    'base',
    # Mail/messaging internals
    'mail.alias',
    'mail.alias.mixin',
    'mail.blacklist',
    'mail.blacklist.mixin',
    'mail.bot',
    'mail.channel',
    'mail.channel.member',
    'mail.channel.rtc.session',
    'mail.compose.message',
    'mail.followers',
    'mail.gateway.allowed',
    'mail.guest',
    'mail.ice.server',
    'mail.link.preview',
    'mail.mail',
    'mail.message.reaction',
    'mail.message.schedule',
    'mail.message.subtype',
    'mail.notification',
    'mail.notification.layout',
    'mail.render.mixin',
    'mail.resend.message',
    'mail.resend.partner',
    'mail.thread',
    'mail.thread.blacklist',
    'mail.thread.cc',
    'mail.thread.main.attachment',
    'mail.thread.phone',
    'mail.tracking.value',
    'mail.wizard.invite',
    # Activities
    'mail.activity.mixin',
    'mail.activity.type',
    # Portal
    'portal.mixin',
    'portal.share',
    'portal.wizard',
    'portal.wizard.user',
    # Format/utilities
    'format.address.mixin',
    'format.vat.mixin',
    'image.mixin',
    'avatar.mixin',
    # Sequences/attachments internals
    'ir.sequence.date_range',
    # Rating
    'rating.mixin',
    'rating.parent.mixin',
    # Resource
    'resource.mixin',
    # UTM
    'utm.mixin',
    # Misc technical
    'barcode.nomenclature',
    'barcode.rule',
    'decimal.precision',
    'res.config',
    'res.config.installer',
    'res.config.settings',
    'change.password.wizard',
    'change.password.user',
}

# Models to completely exclude (truly unusable - no table, abstract, etc.)
# These cannot be queried at all
EXCLUDED_MODELS = {
    '_unknown',
}

# Fields to hide by default (technical/internal but still queryable)
HIDDEN_FIELDS = {
    # ORM technical fields
    '__last_update',
    'display_name',  # Computed, not useful for queries
    # Audit fields
    'create_uid',
    'create_date',
    'write_uid',
    'write_date',
    # Mail/messaging mixin fields
    'message_ids',
    'message_follower_ids',
    'message_partner_ids',
    'message_channel_ids',
    'message_attachment_count',
    'message_has_error',
    'message_has_error_counter',
    'message_has_sms_error',
    'message_is_follower',
    'message_main_attachment_id',
    'message_needaction',
    'message_needaction_counter',
    'message_unread',
    'message_unread_counter',
    'website_message_ids',
    # Activity mixin fields
    'activity_ids',
    'activity_state',
    'activity_user_id',
    'activity_type_id',
    'activity_type_icon',
    'activity_date_deadline',
    'activity_summary',
    'activity_exception_decoration',
    'activity_exception_icon',
    'activity_calendar_event_id',
    'my_activity_date_deadline',
    # Rating mixin
    'rating_ids',
    'rating_last_value',
    'rating_last_feedback',
    'rating_last_image',
    'rating_count',
    'rating_avg',
    'rating_avg_text',
    # Portal mixin
    'access_token',
    'access_url',
    'access_warning',
    # Image mixin variants (computed)
    'image_128',
    'image_256',
    'image_512',
    'image_1024',
    'image_1920',
    # Misc computed/technical
    'has_message',
}


MAX_BATCH_SIZE = 50

# Module version — keep in sync with __manifest__.py.
MODULE_VERSION = '2.0.0'


class OdashboardController(http.Controller):

    @http.route('/odashboard/version', type='http', auth='none', methods=['GET'], csrf=False, readonly=True)
    def get_version(self):
        """Return the module version. No authentication required."""
        return self._json_response({'version': MODULE_VERSION})


    def _authenticate(self):
        """Authenticate the request using Bearer token.
        
        Looks up API keys by hash in the odashboard.api.key model.
        Both default (ODashboard-managed) and custom keys are supported.
        Rate-limited: IPs with too many failed attempts are blocked.
        
        Returns:
            (key_record, None) on success - key_record is the odashboard.api.key record
            (None, error_response) on failure
        """
        # Rate limiting: check if IP is blocked
        forwarded_for = request.httprequest.environ.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            # Take the LAST IP — the one appended by the trusted reverse proxy.
            # The first IP is client-controlled and spoofable.
            client_ip = forwarded_for.split(',')[-1].strip()
        else:
            client_ip = request.httprequest.remote_addr
        if _auth_limiter.is_blocked(client_ip):
            return None, self._error_response('Too many failed attempts. Try again later.', 429)

        auth_header = request.httprequest.headers.get('Authorization', '')

        if not auth_header.startswith('Bearer '):
            return None, self._error_response('Missing or invalid Authorization header', 401)

        api_key = auth_header[7:]  # Remove 'Bearer ' prefix

        # Look up by hash (secure: raw key is never stored after creation)
        ApiKey = request.env['odashboard.api.key'].sudo()
        key_record = ApiKey.authenticate_by_key(api_key)

        if key_record:
            # Usage tracking is handled by ODashboard API (in-memory + periodic flush)
            # so we don't write anything here — keeps endpoints readonly-compatible.
            _auth_limiter.record_success(client_ip)
            return key_record, None

        _auth_limiter.record_failure(client_ip)
        return None, self._error_response('Invalid API key', 401)

    def _json_response(self, data, status=200):
        """Return a JSON response."""
        return Response(
            json.dumps(data, default=str),
            status=status,
            mimetype='application/json'
        )

    def _error_response(self, message, status=400):
        """Return an error JSON response."""
        return self._json_response({'error': True, 'message': message}, status)

    @http.route('/odashboard/schema', type='http', auth='none', methods=['GET'], csrf=False, readonly=True)
    def get_schema(self):
        """
        Get the database schema.
        Returns all models with their fields for the query builder.
        """
        api_key, error = self._authenticate()
        if error:
            return error

        try:
            models_data = self._get_schema_data(api_key)
            return self._json_response({'models': models_data})
        except Exception:
            _logger.exception("Error fetching schema")
            return self._error_response('Internal server error', 500)

    @http.route('/odashboard/query', type='http', auth='none', methods=['POST'], csrf=False, readonly=True)
    def execute_query(self):
        """
        Execute a SELECT query.
        Only SELECT statements are allowed for security.
        """
        api_key, error = self._authenticate()
        if error:
            return error

        try:
            # Parse JSON body
            data = json.loads(request.httprequest.data or '{}')
            query = data.get('query', '').strip()

            if not query:
                return self._error_response('Query is required')

            # Security: Only allow SELECT statements
            if not self._is_select_query(query):
                return self._error_response('Only SELECT queries are allowed', 403)

            # Execute query
            result = self._execute_select(query)
            return self._json_response(result)

        except json.JSONDecodeError:
            return self._error_response('Invalid JSON body')
        except QueryExecutionError as e:
            # SQL error - return detailed info with 400 status
            _logger.warning("Query execution failed: %s", e.error_info.get('message'))
            return self._json_response(e.error_info, status=400)
        except Exception:
            _logger.exception("Error executing query")
            return self._error_response('Internal server error', 500)

    @http.route('/odashboard/query/batch', type='http', auth='none', methods=['POST'], csrf=False, readonly=True)
    def execute_query_batch(self):
        """
        Execute multiple SELECT queries in a single HTTP request.

        Each query is executed independently. Since the endpoint is
        readonly, a failure in one query does not corrupt the cursor —
        errors are caught and returned per-query.

        JSON body:
            queries: list of {"id": str, "query": str}

        Returns:
            {"results": [{"id": str, ...result_or_error...}, ...]}
        """
        api_key, error = self._authenticate()
        if error:
            return error

        try:
            data = json.loads(request.httprequest.data or '{}')
            queries = data.get('queries', [])

            if not isinstance(queries, list) or not queries:
                return self._error_response('queries must be a non-empty array')

            if len(queries) > MAX_BATCH_SIZE:
                return self._error_response(f'Maximum {MAX_BATCH_SIZE} queries per batch')

            results = []
            for item in queries:
                qid = item.get('id', '')
                query = (item.get('query') or '').strip()

                if not query:
                    results.append({'id': qid, 'success': False, 'error': True, 'message': 'Query is required'})
                    continue

                if not self._is_select_query(query):
                    results.append({'id': qid, 'success': False, 'error': True, 'message': 'Only SELECT queries are allowed'})
                    continue

                try:
                    result = self._execute_select(query)
                    result['id'] = qid
                    results.append(result)
                except QueryExecutionError as e:
                    error_info = e.error_info
                    error_info['id'] = qid
                    results.append(error_info)

            return self._json_response({'results': results})

        except json.JSONDecodeError:
            return self._error_response('Invalid JSON body')
        except Exception:
            _logger.exception("Error executing batch query")
            return self._error_response('Internal server error', 500)

    def _should_exclude_model(self, model_name, Model):
        """Check if a model should be completely excluded from schema.
        
        Only truly unusable models are excluded (abstract, transient, no table).
        Other "technical" models are hidden by default but still included.
        """
        # Exclude unknown models
        if model_name in EXCLUDED_MODELS or model_name.startswith('_unknown'):
            return True

        # Exclude abstract models (no table)
        if getattr(Model, '_abstract', False):
            return True

        # Exclude models without auto-created tables (SQL views, etc.)
        if getattr(Model, '_auto', True) is False:
            return True

        return False

    def _should_hide_model(self, model_name):
        """Check if a model should be hidden by default (but still included)."""
        # Check prefix
        for prefix in HIDDEN_MODEL_PREFIXES:
            if model_name.startswith(prefix):
                return True

        # Check exact name
        if model_name in HIDDEN_MODELS:
            return True

        return False

    def _get_schema_data(self, api_key):
        """Build schema data from Odoo models.
        
        Args:
            api_key: An odashboard.api.key record
        """
        IrModel = request.env['ir.model'].sudo()

        # Get all non-transient models
        domain = [('transient', '=', False)]

        # Custom keys can have allowed_models restrictions
        # Default keys (key_type='default') have access to all models
        if not api_key.is_model_allowed('*'):
            # is_model_allowed returns True for default keys or if allowed_models is empty
            # If we get here, the key has restrictions
            if api_key.allowed_models:
                allowed = [m.strip() for m in api_key.allowed_models.split(',')]
                domain.append(('model', 'in', allowed))

        models = IrModel.search(domain)
        models_data = []

        for model in models:
            try:
                # Get the actual model to access _table
                Model = request.env[model.model]
                table_name = Model._table

                # Completely exclude truly unusable models
                if self._should_exclude_model(model.model, Model):
                    continue

            except KeyError:
                continue

            # Check if model should be hidden by default
            model_hidden = self._should_hide_model(model.model)

            fields_data = []

            for field in model.field_id:
                field_info = self._get_field_info(model.model, field)
                if field_info:
                    fields_data.append(field_info)

            # Skip models with no fields at all (after excluding non-stored, etc.)
            if not fields_data:
                continue

            model_data = {
                'model': model.model,
                'name': model.name,
                'table': table_name,
                'description': model.info or '',
                'fields': fields_data,
            }

            # Add hidden flag
            if model_hidden:
                model_data['hidden'] = True

            models_data.append(model_data)

        return models_data

    def _get_field_info(self, model_name, field):
        """Get field information for schema."""
        try:
            Model = request.env[model_name]
            field_obj = Model._fields.get(field.name)

            if not field_obj:
                return None

            # Check if field is stored (queryable in SQL)
            is_stored = getattr(field_obj, 'store', True)

            # Skip non-stored fields (computed without store=True)
            # Exception: keep 'id' which is always useful
            if not is_stored and field.name != 'id':
                return None

            # Skip inherited fields from _inherits (they exist in parent table, not this one)
            # e.g., res.users inherits from res.partner, so 'name' is in res_partner, not res_users
            # Exception: keep audit fields (create_uid, create_date, write_uid, write_date)
            # as they exist in every table even if technically "inherited"
            AUDIT_FIELDS = {'create_uid', 'create_date', 'write_uid', 'write_date'}
            if getattr(field_obj, 'inherited_field', None) and field.name not in AUDIT_FIELDS:
                return None

            # Skip related fields that point to another model
            # (they don't have their own column in the table)
            related = getattr(field_obj, 'related', None)
            if related and is_stored:
                # Check if it's a cross-model related field
                related_parts = related.split('.') if isinstance(related, str) else related
                if len(related_parts) > 1:
                    # It's a related field like partner_id.name - the data is in another table
                    return None

            # Binary fields - include but hidden by default (large, rarely useful for queries)
            is_binary = field.ttype == 'binary'

            # Check if field should be hidden by default
            field_hidden = field.name in HIDDEN_FIELDS or is_binary

            # Basic field info
            info = {
                'name': field.name,
                'string': field.field_description,
                'type': field.ttype,
                'required': field.required,
            }

            # Add hidden flag if applicable
            if field_hidden:
                info['hidden'] = True

            # Relation info for many2one fields
            if field.ttype == 'many2one':
                info['relation'] = field.relation
                if field.relation:
                    try:
                        RelModel = request.env[field.relation]
                        # Check if the related model would be excluded
                        if not self._should_exclude_model(field.relation, RelModel):
                            info['relation_table'] = RelModel._table
                        else:
                            # Related model is excluded, still keep the field
                            # but mark relation_table as None
                            info['relation_table'] = None
                    except KeyError:
                        info['relation_table'] = None

            # Relation info for one2many fields (inverse relation)
            if field.ttype == 'one2many':
                comodel_name = getattr(field_obj, 'comodel_name', None) or field.relation
                inverse_name = getattr(field_obj, 'inverse_name', None)
                if comodel_name and inverse_name:
                    try:
                        RelModel = request.env[comodel_name]
                        if not self._should_exclude_model(comodel_name, RelModel):
                            info['relation'] = comodel_name
                            info['relation_table'] = RelModel._table
                            info['inverse_column'] = inverse_name
                        else:
                            info['relation'] = comodel_name
                            info['relation_table'] = None
                    except KeyError:
                        info['relation'] = comodel_name
                        info['relation_table'] = None
                else:
                    # Cannot resolve inverse metadata, skip this field
                    return None

            # Relation info for many2many fields (navigable via junction table)
            if field.ttype == 'many2many':
                comodel_name = getattr(field_obj, 'comodel_name', None) or field.relation
                if comodel_name:
                    try:
                        RelModel = request.env[comodel_name]
                        if not self._should_exclude_model(comodel_name, RelModel):
                            info['relation'] = comodel_name
                            info['relation_table'] = RelModel._table
                            # Junction table metadata for building the double JOIN
                            junction_table = getattr(field_obj, 'relation', None)
                            column1 = getattr(field_obj, 'column1', None)
                            column2 = getattr(field_obj, 'column2', None)
                            if junction_table and column1 and column2:
                                info['junction_table'] = junction_table
                                info['junction_source_column'] = column1
                                info['junction_target_column'] = column2
                            else:
                                # Cannot resolve junction metadata, skip this field
                                return None
                        else:
                            info['relation'] = comodel_name
                            info['relation_table'] = None
                    except KeyError:
                        info['relation'] = comodel_name
                        info['relation_table'] = None

            # Selection options
            if field.ttype == 'selection':
                try:
                    selection = field_obj.selection
                    if callable(selection):
                        selection = selection(Model)
                    info['selection'] = selection
                except Exception:
                    info['selection'] = []

            # Currency field for monetary
            if field.ttype == 'monetary':
                info['currency_field'] = getattr(field_obj, 'currency_field', 'currency_id')

            return info

        except Exception as e:
            _logger.warning("Error getting field info for %s.%s: %s", model_name, field.name, e)
            return None

    def _is_select_query(self, query):
        """Check if the query is a SELECT statement (security check).
        
        This method performs several security validations:
        1. Removes SQL comments to prevent bypass via comment injection
        2. Checks for multiple statements (semicolons)
        3. Ensures query starts with SELECT or WITH (CTE)
        4. Blocks dangerous keywords that could modify data
        
        Returns:
            bool: True if the query is a safe SELECT, False otherwise
        """
        # Step 1: Remove SQL comments to prevent bypass attacks
        # Remove single-line comments (-- comment)
        query_no_comments = re.sub(r'--[^\n]*', '', query)
        # Remove multi-line comments (/* comment */)
        query_no_comments = re.sub(r'/\*.*?\*/', '', query_no_comments, flags=re.DOTALL)
        
        # Step 2: Check for multiple statements (semicolon outside of quotes)
        # This regex finds semicolons that are not inside single or double quotes
        # Pattern explanation: ; followed by any chars, checking we have balanced quotes
        if self._contains_multiple_statements(query_no_comments):
            return False
        
        # Step 3: Normalize whitespace for keyword checking
        normalized = ' '.join(query_no_comments.split()).upper()
        
        if not normalized:
            return False

        # Must start with SELECT or WITH (for CTEs)
        # CTEs: WITH ... AS (...) SELECT ...
        if not (normalized.startswith('SELECT ') or normalized.startswith('WITH ')):
            return False

        # For CTEs, ensure there's a SELECT somewhere after WITH
        if normalized.startswith('WITH ') and ' SELECT ' not in normalized:
            return False

        # Step 4: Check for forbidden keywords that could modify data.
        # Use word-boundary regex to avoid false positives on identifiers
        # like "date_last_stage_update" matching "UPDATE".
        forbidden = [
            'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER',
            'CREATE', 'TRUNCATE', 'GRANT', 'REVOKE',
            'EXECUTE', 'EXEC', 'CALL', 'COPY',
            'LOCK', 'VACUUM', 'ANALYZE', 'REINDEX',
            'CLUSTER', 'REFRESH', 'SECURITY', 'EXPLAIN',
            'DO', 'COMMENT', 'LOAD', 'LISTEN', 'NOTIFY',
            'PREPARE', 'DEALLOCATE', 'IMPORT',
        ]
        # Dangerous PostgreSQL functions that could bypass security controls.
        # set_config: can disable statement_timeout or change session settings.
        # pg_sleep: denial of service (even within timeout window).
        # pg_read_file/pg_ls_dir/lo_import: filesystem access (requires superuser
        # but blocked as defense-in-depth).
        forbidden_functions = [
            'SET_CONFIG',
            'PG_SLEEP',
            'PG_READ_FILE',
            'PG_READ_BINARY_FILE',
            'PG_LS_DIR',
            'LO_IMPORT',
            'LO_EXPORT',
            'DBLINK',
            'DBLINK_EXEC',
            'DBLINK_CONNECT',
            'PG_TERMINATE_BACKEND',
            'PG_CANCEL_BACKEND',
            'PG_STAT_FILE',
        ]
        # Build a single regex: (?<![A-Z_])KEYWORD(?![A-Z_])
        # This ensures the keyword is not part of a larger identifier.
        pattern = r'(?<![A-Z_])(?:' + '|'.join(forbidden) + r')(?![A-Z_])'
        if re.search(pattern, normalized):
            return False

        # Block dangerous PostgreSQL functions (called as function_name(...))
        func_pattern = r'(?<![A-Z_])(?:' + '|'.join(forbidden_functions) + r')\s*\('
        if re.search(func_pattern, normalized):
            return False

        # Also block double-quoted function calls (e.g., "set_config"(...))
        # which bypass the above pattern since the quote appears between name and paren.
        quoted_func_pattern = r'"(?:' + '|'.join(forbidden_functions) + r')"\s*\('
        if re.search(quoted_func_pattern, normalized):
            return False

        # Also check multi-word keywords separately
        if re.search(r'(?<![A-Z_])SET\s+ROLE(?![A-Z_])', normalized):
            return False

        return True
    
    def _contains_multiple_statements(self, query):
        """Check if query contains multiple SQL statements.
        
        Detects semicolons that are not inside string literals or
        dollar-quoted strings. Handles PostgreSQL quoting correctly:
        - Single quotes: standard SQL escaping via '' (NOT backslash)
        - Double quotes: identifier quoting
        - Dollar quotes: $tag$...$tag$ (PostgreSQL-specific)
        
        Args:
            query: The SQL query string (with comments already removed)
            
        Returns:
            bool: True if multiple statements detected, False otherwise
        """
        in_single_quote = False
        in_double_quote = False
        dollar_tag = None  # Active dollar-quote tag (e.g., "$$" or "$tag$")
        i = 0
        
        while i < len(query):
            char = query[i]

            # --- Dollar-quoted strings ($tag$...$tag$) ---
            if dollar_tag is not None:
                # Inside a dollar-quoted string — look for closing tag
                if char == '$':
                    end = query.find('$', i + 1)
                    if end != -1:
                        candidate = query[i:end + 1]
                        if candidate == dollar_tag:
                            dollar_tag = None
                            i = end + 1
                            continue
                i += 1
                continue

            if char == '$' and not in_single_quote and not in_double_quote:
                # Detect dollar-quote opening: $$ or $tag$
                end = query.find('$', i + 1)
                if end != -1:
                    tag_content = query[i + 1:end]
                    # Dollar-quote tags must be empty or valid identifiers
                    if tag_content == '' or re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', tag_content):
                        dollar_tag = query[i:end + 1]
                        i = end + 1
                        continue
            
            # --- Standard quote tracking ---
            if char == "'" and not in_double_quote:
                # Check for escaped quote '' (standard SQL escaping)
                if in_single_quote and i + 1 < len(query) and query[i + 1] == "'":
                    i += 2
                    continue
                in_single_quote = not in_single_quote
            elif char == '"' and not in_single_quote:
                if in_double_quote and i + 1 < len(query) and query[i + 1] == '"':
                    i += 2
                    continue
                in_double_quote = not in_double_quote
            elif char == ';' and not in_single_quote and not in_double_quote:
                # Found a semicolon outside of quotes
                # Check if there's meaningful content after it
                remaining = query[i + 1:].strip()
                if remaining:
                    return True
            
            i += 1
        
        return False

    # Query execution limits
    MAX_QUERY_TIMEOUT_MS = 30000  # 30 seconds
    MAX_ROWS = 50000  # Maximum rows to return

    def _execute_select(self, query):
        """Execute a SELECT query and return results.

        Since the endpoints are readonly=True, the cursor is on a read-only
        replica. No savepoint management is needed — if the query fails we
        simply catch the error and return it. The readonly cursor cannot be
        corrupted by a failed SELECT.
        """
        start_time = time.time()
        cr = request.env.cr

        try:
            # Set statement timeout to prevent long-running queries
            cr.execute(f'SET LOCAL statement_timeout = {self.MAX_QUERY_TIMEOUT_MS}')
            cr.execute(query)

            # Get column names
            columns = [
                {'name': desc[0], 'type': self._pg_type_to_string(desc[1])}
                for desc in cr.description
            ]

            # Fetch rows with limit to prevent memory exhaustion
            rows = cr.fetchmany(self.MAX_ROWS)
            has_more = cr.fetchone() is not None

            execution_time = int((time.time() - start_time) * 1000)

            result = {
                'success': True,
                'columns': columns,
                'rows': rows,
                'row_count': len(rows),
                'execution_time_ms': execution_time,
            }

            if has_more:
                result['truncated'] = True
                result['max_rows'] = self.MAX_ROWS

            return result

        except psycopg2.Error as e:
            execution_time = int((time.time() - start_time) * 1000)

            # Extract useful error info
            error_info = {
                'success': False,
                'error': True,
                'error_type': type(e).__name__,
                'message': str(e.pgerror) if hasattr(e, 'pgerror') and e.pgerror else str(e),
                'execution_time_ms': execution_time,
            }

            # Add position info if available (helps locate the error in the query)
            if hasattr(e, 'diag') and e.diag:
                diag = e.diag
                if diag.column_name:
                    error_info['column'] = diag.column_name
                if diag.table_name:
                    error_info['table'] = diag.table_name
                if diag.message_detail:
                    error_info['detail'] = diag.message_detail
                if diag.message_hint:
                    error_info['hint'] = diag.message_hint

            raise QueryExecutionError(error_info)

    def _pg_type_to_string(self, pg_type):
        """Convert PostgreSQL type OID to string type."""
        # Common PostgreSQL type OIDs
        type_map = {
            16: 'boolean',
            20: 'integer',  # bigint
            21: 'integer',  # smallint
            23: 'integer',  # integer
            25: 'string',   # text
            700: 'float',   # real
            701: 'float',   # double
            1042: 'string', # char
            1043: 'string', # varchar
            1082: 'date',
            1114: 'datetime',
            1184: 'datetime',  # timestamptz
            1700: 'float',  # numeric
        }
        return type_map.get(pg_type, 'string')

    # =========================================================================
    # RECORD SEARCH (for relation filter value lookup)
    # =========================================================================

    @http.route('/odashboard/search', type='http', auth='none', methods=['POST'], csrf=False, readonly=True)
    def search_records(self):
        """
        Search records by name for relation filter value selection.

        Uses Odoo's name_search to find matching records.

        JSON body:
            model: str - The Odoo model name (e.g., "res.partner")
            search: str - The search term (matched against name/display_name)
            limit: int - Maximum number of results (default 20, max 100)

        Returns:
            {"results": [{"id": 1, "display_name": "Azure Interior"}, ...]}
        """
        api_key, error = self._authenticate()
        if error:
            return error

        try:
            data = json.loads(request.httprequest.data or '{}')
            model_name = data.get('model', '').strip()
            search_term = data.get('search', '').strip()
            limit = min(int(data.get('limit', 20)), 100)

            if not model_name:
                return self._error_response('model is required')

            # Check if API key allows access to this model
            if not api_key.is_model_allowed(model_name):
                return self._error_response(f'Access denied for model: {model_name}', 403)

            # Verify model exists and is accessible
            IrModel = request.env['ir.model'].sudo()
            model_record = IrModel.search([('model', '=', model_name)], limit=1)
            if not model_record:
                return self._error_response(f'Model not found: {model_name}', 404)

            # Use name_search for efficient search (respects _rec_name)
            Model = request.env[model_name].sudo()
            results = Model.name_search(name=search_term, limit=limit)

            # name_search returns [(id, display_name), ...]
            formatted = [
                {'id': r[0], 'display_name': r[1]}
                for r in results
            ]

            return self._json_response({'results': formatted})

        except KeyError as ke:
            return self._error_response(f'Model not available: {ke!s}', 404)
        except Exception:
            _logger.exception("Error searching records")
            return self._error_response('Internal server error', 500)

    # =========================================================================
    # USAGE TRACKING (called by ODashboard API periodically)
    # =========================================================================

    @http.route('/odashboard/usage', type='http', auth='none', methods=['POST'], csrf=False)
    def report_usage(self):
        """
        Receive aggregated API usage stats from ODashboard.

        ODashboard accumulates query counts in-memory and periodically
        flushes them here. This avoids writing on every query execution
        and keeps the query/search endpoints readonly.

        JSON body:
            count: int - Number of queries executed since last flush

        Returns:
            {"success": true}
        """
        api_key, error = self._authenticate()
        if error:
            return error

        try:
            data = json.loads(request.httprequest.data or '{}')
            count = int(data.get('count', 0))

            if count > 0:
                request.env.cr.execute("""
                    UPDATE odashboard_api_key
                    SET last_used = NOW() AT TIME ZONE 'UTC',
                        usage_count = usage_count + %s
                    WHERE id = %s
                """, [count, api_key.id])

            return self._json_response({'success': True})

        except json.JSONDecodeError:
            return self._error_response('Invalid JSON body')
        except Exception:
            _logger.exception("Error reporting usage")
            return self._error_response('Internal server error', 500)

    # =========================================================================
    # API KEY ROTATION (called by ODashboard during sync)
    # =========================================================================

    @http.route('/odashboard/rotate-api-key', type='json', auth='none', methods=['POST'], csrf=False)
    def rotate_api_key(self, instance_key=None, current_api_key=None, **kwargs):
        """
        Rotate the default API key for ODashboard synchronization.
        
        This endpoint is called by ODashboard during the sync process.
        It validates the instance_key and optionally the current_api_key,
        then generates and returns a new API key.
        
        The API key is stored in the odashboard.api.key model with key_type='default'.
        
        JSON-RPC request params:
            instance_key: str - The instance key configured in Odoo settings
            current_api_key: str | None - The current API key (for validation on rotation)
        
        Returns:
            {"api_key": "new-api-key"} on success
            {"error": "message"} on failure
        """
        try:
            if not instance_key:
                return {'error': 'instance_key is required'}

            ICP = request.env['ir.config_parameter'].sudo()
            ApiKey = request.env['odashboard.api.key'].sudo()
            
            # Validate instance_key
            stored_instance_key = ICP.get_param('odashboard.instance_key', default='')
            if not stored_instance_key:
                return {'error': "O'Dashboard is not configured on this Odoo instance"}
            
            if not hmac.compare_digest(instance_key, stored_instance_key):
                return {'error': 'Invalid instance key'}

            # If current_api_key provided, validate it via hash (extra security for rotations)
            if current_api_key:
                default_key = ApiKey.search([
                    ('key_type', '=', 'default'),
                    ('active', '=', True),
                ], limit=1)
                if default_key:
                    current_hash = ApiKey._hash_key(current_api_key)
                    if not hmac.compare_digest(default_key.key_hash or '', current_hash):
                        return {'error': 'Invalid current API key'}

            # Rotate the default API key using the model method
            new_api_key = ApiKey.rotate_default_key()

            _logger.info("ODashboard default API key rotated successfully")
            return {'api_key': new_api_key}

        except Exception:
            _logger.exception("Error rotating API key")
            return {'error': 'Internal server error during key rotation'}

    # =========================================================================
    # DISCONNECT (called by ODashboard when rotating instance key)
    # =========================================================================

    @http.route('/odashboard/disconnect', type='json', auth='none', methods=['POST'], csrf=False)
    def disconnect(self, instance_key=None, **kwargs):
        """
        Disconnect ODashboard from this Odoo instance.

        Called by ODashboard backend before rotating the instance key.
        Validates instance_key, then clears all local ODashboard state
        (connected flag, instance_identifier, synced URL, default API keys).

        JSON-RPC request params:
            instance_key: str - The current instance key (for validation)

        Returns:
            {"status": "ok"} on success
            {"error": "message"} on failure
        """
        try:
            if not instance_key:
                return {'error': 'instance_key is required'}

            ICP = request.env['ir.config_parameter'].sudo()

            stored_instance_key = ICP.get_param('odashboard.instance_key', default='')
            if not stored_instance_key:
                return {'error': "O'Dashboard is not configured on this Odoo instance"}

            if not hmac.compare_digest(instance_key, stored_instance_key):
                return {'error': 'Invalid instance key'}

            # Clear all connection state
            ICP.set_param('odashboard.instance_key', '')
            ICP.set_param('odashboard.instance_identifier', '')
            ICP.set_param('odashboard.synced_odoo_url', '')
            ICP.set_param('odashboard.connected', '')

            # Delete default API keys
            ApiKey = request.env['odashboard.api.key'].sudo()
            default_keys = ApiKey.search([('key_type', '=', 'default')])
            if default_keys:
                default_keys.unlink()

            _logger.info("ODashboard disconnected via remote call")
            return {'status': 'ok'}

        except Exception:
            _logger.exception("Error during ODashboard disconnect")
            return {'error': 'Internal server error during disconnect'}

    # =========================================================================
    # IFRAME TOKEN GENERATION (for embedding dashboards)
    # =========================================================================

    @http.route('/odashboard/iframe-token', type='json', auth='user', methods=['POST'], csrf=False)
    def generate_iframe_token(self, **kwargs):
        """
        Generate a signed HMAC token for iframe authentication.
        
        This endpoint is called by Odoo to generate a token that can be used
        to authenticate users in an embedded ODashboard iframe.
        
        The token contains:
        - instance_identifier: Public UUID identifying the instance (received during sync)
        - instance_url: The Odoo instance URL
        - odoo_uid: The current user's Odoo ID
        - timestamp: Current Unix timestamp
        - signature: HMAC-SHA256 of "{instance_identifier}:{instance_url}:{odoo_uid}:{timestamp}"
        
        Returns:
            {
                "token": {
                    "instance_identifier": "uuid-...",
                    "instance_url": "https://myodoo.com",
                    "odoo_uid": "123",
                    "odoo_name": "John Doe",
                    "odoo_login": "john@example.com",
                    "timestamp": "1234567890",
                    "signature": "abc123..."
                },
                "odashboard_url": "https://api.odashboard.app",
                "frontend_url": "https://app.odashboard.app"
            }
        """
        try:
            ICP = request.env['ir.config_parameter'].sudo()
            
            # Get configuration
            instance_key = ICP.get_param('odashboard.instance_key', default='')
            api_url = ICP.get_param('odashboard.api_url', default='')
            frontend_url = ICP.get_param('odashboard.frontend_url', default='')
            instance_url = ICP.get_param('web.base.url', default='')
            
            # URL-level config: if api_url or frontend_url is missing,
            # the iframe can't load at all → show Odoo-native setup screen.
            missing_urls = []
            if not api_url:
                missing_urls.append('api_url')
            if not frontend_url:
                missing_urls.append('frontend_url')

            if missing_urls:
                return {
                    'error': 'not_configured',
                    'missing': missing_urls,
                }

            # Not connected: either instance_key is missing, or the sync
            # hasn't been done yet → load the in-app setup/onboarding page.
            is_connected = ICP.get_param('odashboard.connected', default='') == 'true'
            if not instance_key or not is_connected:
                return {
                    'needs_setup': True,
                    'frontend_url': frontend_url.rstrip('/'),
                }

            # instance_identifier is a public UUID received during sync.
            # It uniquely identifies the instance without exposing the secret key.
            instance_identifier = ICP.get_param('odashboard.instance_identifier', default='')
            if not instance_identifier:
                # If missing (pre-upgrade instances), force a re-sync
                return {
                    'needs_setup': True,
                    'frontend_url': frontend_url.rstrip('/'),
                }

            if not instance_url:
                return {'error': 'Odoo base URL not configured'}
            
            # Build token payload
            user = request.env.user
            odoo_uid = str(user.id)
            timestamp = str(int(time.time()))
            
            # Resolve related IDs for current user context variables
            # partner_id: always available (res.users inherits res.partner)
            odoo_partner_id = str(user.partner_id.id) if user.partner_id else ''
            
            # employee_id: only if hr module is installed
            odoo_employee_id = ''
            try:
                if hasattr(user, 'employee_id') and user.employee_id:
                    odoo_employee_id = str(user.employee_id.id)
                elif hasattr(user, 'employee_ids') and user.employee_ids:
                    odoo_employee_id = str(user.employee_ids[0].id)
            except Exception:
                pass  # hr module not installed or employee not linked
            
            # Generate HMAC signature
            # Format: instance_identifier:instance_url:odoo_uid:timestamp
            # instance_identifier ensures unique instance lookup.
            # instance_url is kept for additional security (binds token to URL).
            # Note: odoo_name, odoo_login, odoo_partner_id, odoo_employee_id
            # are NOT part of the HMAC message to keep signature verification
            # simple and stable.
            message = f"{instance_identifier}:{instance_url}:{odoo_uid}:{timestamp}"
            signature = hmac.new(
                instance_key.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            return {
                'token': {
                    'instance_identifier': instance_identifier,
                    'instance_url': instance_url,
                    'odoo_uid': odoo_uid,
                    'odoo_name': user.name or '',
                    'odoo_login': user.login or '',
                    'odoo_partner_id': odoo_partner_id,
                    'odoo_employee_id': odoo_employee_id,
                    'lang': user.lang or '',
                    'timestamp': timestamp,
                    'signature': signature,
                },
                'odashboard_url': api_url.rstrip('/'),
                'frontend_url': frontend_url.rstrip('/'),
            }
            
        except Exception:
            _logger.exception("Error generating iframe token")
            return {'error': 'Internal server error'}
