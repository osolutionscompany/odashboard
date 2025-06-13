"""
Developer API file
"""

import json
import logging
import itertools
from datetime import datetime, date, timedelta
import calendar
import re
from dateutil.relativedelta import relativedelta

from odoo import api

from odoo import http
from odoo.http import request, Response

from .api_helper import ApiHelper

_logger = logging.getLogger(__name__)


class OdashboardJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super(OdashboardJSONEncoder, self).default(obj)


class OdashboardAPI(http.Controller):

    @http.route(['/api/odash/access'], type='http', auth='none', csrf=False, methods=['GET'], cors="*")
    def get_access(self, **kw):
        token = request.env['ir.config_parameter'].sudo().get_param('odashboard.api.token')
        return ApiHelper.json_valid_response(token, 200)

    @http.route(['/api/osolution/refresh-token/<string:uuid>/<string:key>'], type='http', auth='none', csrf=False,
                methods=['GET'], cors="*")
    def refresh_token(self, uuid, key, **kw):
        uuid_param = request.env['ir.config_parameter'].sudo().get_param('odashboard.uuid')
        key_param = request.env['ir.config_parameter'].sudo().get_param('odashboard.key')

        if uuid_param == uuid and key_param == key:
            request.env["odash.dashboard"].sudo().update_auth_token()
        return ApiHelper.json_valid_response("ok", 200)

    @http.route(['/api/get/models'], type='http', auth='none', csrf=False, methods=['GET'], cors="*")
    def get_models(self, **kw):
        """
        Return a list of models relevant for analytics, automatically filtering out technical models

        :return: JSON response with list of analytically relevant models
        """
        try:
            _logger.info("API call: Fetching list of analytically relevant models")

            # Create domain to filter models directly in the search
            # 1. Must be non-transient
            domain = [('transient', '=', False)]

            # 2. Exclude technical models using NOT LIKE conditions
            technical_prefixes = ['ir.', 'base.', 'bus.', 'base_import.',
                                  'web.', 'mail.', 'auth.', 'report.',
                                  'resource.', 'wizard.']
            for prefix in technical_prefixes:
                domain.append(('model', 'not like', f'{prefix}%'))

            # Models starting with underscore
            domain.append(('model', 'not like', '\\_%'))

            """
            # TODO : Améliorer le filtrage des modèles
                     # 3. Include only analytical models using OR conditions with LIKE
            analytical_domain = ['|'] * (14 - 1)  # 13 patterns minus 1
            analytical_domain += [
                ('model', 'like', 'sale.%'),
                ('model', 'like', 'account.%'),
                ('model', 'like', 'crm.%'),
                ('model', 'like', 'product.%'),
                ('model', 'like', 'purchase.%'),
                ('model', 'like', 'stock.%'),
                ('model', 'like', 'project.%'),
                ('model', 'like', 'hr.%'),
                ('model', 'like', 'pos.%'),
                ('model', 'like', 'mrp.%'),
                ('model', 'like', 'website_sale.%'),
                ('model', 'like', 'event.%'),
                ('model', 'like', 'marketing.%'),
                ('model', 'like', 'res.%'),
            ]

            # Combine all conditions
            domain = domain + analytical_domain

            """

            # Execute the optimized search
            model_obj = request.env['ir.model'].sudo()
            models = model_obj.search(domain)

            _logger.info("Found %s analytical models", len(models))

            # Format the response with the already filtered models
            model_list = [{
                'name': model.name,
                'model': model.model,
            } for model in models]

            return ApiHelper.json_valid_response(model_list, 200)

        except Exception as e:
            _logger.error("Error in API get_models: %s", str(e))
            error_response = {
                'success': False,
                'error': str(e)
            }
            response = Response(
                json.dumps(error_response, cls=OdashboardJSONEncoder),
                content_type='application/json',
                status=500
            )
            return response

    @http.route(['/api/get/model_fields/<string:model_name>'], type='http', auth='none', csrf=False,
                methods=['GET'], cors="*")
    def get_model_fields(self, model_name, **kw):
        """
        Retrieve information about the fields of a specific Odoo model.

        :param model_name: Name of the Odoo model (example: 'sale.order')
        :return: JSON with information about the model's fields
        """
        try:
            _logger.info("API call: Fetching fields info for model: %s", model_name)

            # Check if the model exists
            if model_name not in request.env:
                return self._build_response({'success': False, 'error': f"Model '{model_name}' not found"}, status=404)

            # Get field information
            model_obj = request.env[model_name].sudo()
            fields_info = self._get_fields_info(model_obj)

            return self._build_response(fields_info, 200)

        except Exception as e:
            _logger.error("Error in API get_model_fields: %s", str(e))
            return self._build_response({'success': False, 'error': str(e)}, status=500)

    def _get_fields_info(self, model):
        """
        Get information about all fields of an Odoo model.
        
        :param model: Odoo model object
        :return: List of field information
        """
        fields_info = []

        # Get fields from the model
        fields_data = model.fields_get()

        # Fields to exclude
        excluded_field_types = ['binary', 'one2many', 'many2many', 'text']  # Binary fields like images in base64
        excluded_field_names = [
            '__last_update',
            'write_date', 'write_uid', 'create_uid',
        ]

        # Fields prefixed with these strings will be excluded
        excluded_prefixes = ['message_', 'activity_', 'has_', 'is_', 'x_studio_']

        for field_name, field_data in fields_data.items():
            field_type = field_data.get('type', 'unknown')

            # Skip fields that match our exclusion criteria
            if (field_type in excluded_field_types or
                    field_name in excluded_field_names or
                    any(field_name.startswith(prefix) for prefix in excluded_prefixes)):
                continue

            # Check if it's a computed field that's not stored
            field_obj = model._fields.get(field_name)
            if field_obj and field_obj.compute and not field_obj.store:
                _logger.debug("Skipping non-stored computed field: %s", field_name)
                continue

            # Create field info object for response
            field_info = {
                'field': field_name,
                'name': field_data.get('string', field_name),
                'type': field_type,
                'label': field_data.get('string', field_name),
                'value': field_name,
                'search': f"{field_name} {field_data.get('string', field_name)}"
            }

            # Add selection options if field is a selection
            if field_data.get('type') == 'selection' and 'selection' in field_data:
                field_info['selection'] = [
                    {'value': value, 'label': label}
                    for value, label in field_data['selection']
                ]

            fields_info.append(field_info)

        # Sort fields by name for better readability
        fields_info.sort(key=lambda x: x['name'])

        return fields_info

    @http.route('/api/get/dashboard', type='http', auth='none', csrf=False, methods=['POST'], cors='*')
    def get_dashboard_data(self):
        """Main endpoint to get dashboard visualization data.
        Accepts JSON configurations for blocks, graphs, and tables.
        """
        results = {}

        try:
            # Parse JSON request data
            try:
                request_data = json.loads(request.httprequest.data.decode('utf-8'))
                if not isinstance(request_data, list):
                    request_data = [request_data]
            except Exception as e:
                _logger.error("Error parsing JSON data: %s", e)
                return self._build_response({'error': 'Invalid JSON format'}, 400)

            # Process each visualization request
            for config in request_data:
                config_id = config.get('id')
                if not config_id:
                    continue

                try:
                    # Extract configuration parameters
                    viz_type = config.get('type')
                    model_name = config.get('model')
                    data_source = config.get('data_source', {})

                    # Validate essential parameters
                    if not all([viz_type, model_name]):
                        results[config_id] = {'error': 'Missing required parameters: type, model'}
                        continue

                    # Check if model exists
                    try:
                        model = request.env[model_name].sudo()
                    except KeyError:
                        results[config_id] = {'error': f'Model not found: {model_name}'}
                        continue

                    # Extract common parameters
                    domain = data_source.get('domain', [])
                    group_by = data_source.get('groupBy', [])
                    order_by = data_source.get('orderBy', {})
                    order_string = None
                    if order_by:
                        field = order_by.get('field')
                        direction = order_by.get('direction', 'asc')
                        if field:
                            order_string = f"{field} {direction}"

                    # Check if SQL request is provided
                    sql_request = data_source.get('sqlRequest')

                    if sql_request:
                        """Exécute une requête SQL en annulant toute modification éventuelle."""
                        with request.env.cr.savepoint():
                            # This creates a savepoint, executes the code, and releases the savepoint
                            results[config_id] = self._process_sql_request(sql_request, viz_type, config)
                            # No need for explicit rollback, changes are isolated in the savepoint
                    elif viz_type == 'block':
                        results[config_id] = self._process_block(model, domain, config)
                    elif viz_type == 'graph':
                        results[config_id] = self._process_graph(model, domain, group_by, order_string, config)
                    elif viz_type == 'table':
                        results[config_id] = self._process_table(model, domain, group_by, order_string, config)
                    else:
                        results[config_id] = {'error': f'Unsupported visualization type: {viz_type}'}

                except Exception as e:
                    _logger.exception("Error processing visualization %s:", config_id)
                    results[config_id] = {'error': str(e)}

            return self._build_response([results], 200)

        except Exception as e:
            _logger.exception("Unhandled error in get_dashboard_data:")
            return self._build_response({'error': str(e)}, 500)

    def _build_response(self, data, status=200):
        """Build a consistent JSON response with the given data and status."""
        headers = {'Content-Type': 'application/json'}
        return Response(json.dumps(data, cls=OdashboardJSONEncoder),
                        status=status,
                        headers=headers)

    def _parse_date_from_string(self, date_str, return_range=False):
        """Parse a date string in various formats and return a datetime object.
        If return_range is True, return a tuple of start and end dates for period formats.
        """
        if not date_str:
            return None

        # Week pattern (e.g., W16 2025)
        week_pattern = re.compile(r'W(\d{1,2})\s+(\d{4})')
        week_match = week_pattern.match(date_str)
        if week_match:
            week_num = int(week_match.group(1))
            year = int(week_match.group(2))
            # Get the first day of the week
            first_day = datetime.strptime(f'{year}-{week_num}-1', '%Y-%W-%w').date()
            if return_range:
                last_day = first_day + timedelta(days=6)
                return first_day, last_day
            return first_day

        # Month pattern (e.g., January 2025 or 2025-01)
        month_pattern = re.compile(r'(\w+)\s+(\d{4})|(\d{4})-(\d{2})')
        month_match = month_pattern.match(date_str)
        if month_match:
            if month_match.group(1) and month_match.group(2):
                # Format: January 2025
                month_name = month_match.group(1)
                year = int(month_match.group(2))
                month_num = datetime.strptime(month_name, '%B').month
            else:
                # Format: 2025-01
                year = int(month_match.group(3))
                month_num = int(month_match.group(4))

            if return_range:
                first_day = date(year, month_num, 1)
                last_day = date(year, month_num, calendar.monthrange(year, month_num)[1])
                return first_day, last_day
            return date(year, month_num, 1)

        # Standard date format
        try:
            parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            if return_range:
                return parsed_date, parsed_date
            return parsed_date
        except ValueError:
            pass

        # ISO format
        try:
            parsed_date = datetime.fromisoformat(date_str).date()
            if return_range:
                return parsed_date, parsed_date
            return parsed_date
        except ValueError:
            pass

        return None

    def _get_field_values(self, model, field_name, domain=None):
        """Get all possible values for a field in the model."""
        domain = domain or []
        field_info = model._fields.get(field_name)

        if not field_info:
            return []

        if field_info.type == 'selection':
            # Return all selection options
            return [key for key, _ in field_info.selection]

        elif field_info.type == 'many2one':
            # Return all possible values for the relation
            relation_model = model.env[field_info.comodel_name]
            rel_values = relation_model.search_read([], ['id', 'display_name'])
            return [{'id': r['id'], 'display_name': r['display_name']} for r in rel_values]

        elif field_info.type in ['date', 'datetime']:
            # Cette partie est gérée séparément avec _build_date_range
            # basé sur l'intervalle et le domaine
            return []

        else:
            # Pour les autres types de champs, récupérer toutes les valeurs existantes
            records = model.search(domain)
            # Filtrer les valeurs None pour éviter les problèmes
            values = [v for v in list(set(records.mapped(field_name))) if v is not None]
            return values

    def _build_date_range(self, model, field_name, domain, interval='month'):
        """Build a range of dates for show_empty functionality."""
        # Approche plus simple et robuste - ignorer les requêtes SQL complexes
        # et travailler directement avec les données du modèle
        try:
            # Définir une plage par défaut (derniers 3 mois)
            today = date.today()
            default_min_date = today - relativedelta(months=3)
            default_max_date = today

            # Récupérer tous les enregistrements correspondant au domaine
            # et extraire les min/max dates directement des données Python
            records = model.search(domain or [])
            if records:
                date_values = []
                # Extraire les valeurs de date de tous les enregistrements
                for record in records:
                    field_value = record[field_name]
                    if field_value:
                        # Convertir en date si c'est un datetime
                        if isinstance(field_value, datetime):
                            field_value = field_value.date()
                        date_values.append(field_value)

                if date_values:
                    min_date = min(date_values)
                    max_date = max(date_values)
                else:
                    min_date = default_min_date
                    max_date = default_max_date
            else:
                # Pas de données - utiliser les dates par défaut
                min_date = default_min_date
                max_date = default_max_date

            # Limiter à 1 an maximum pour éviter les plages trop grandes
            if (max_date - min_date).days > 365:
                max_date = min_date + timedelta(days=365)
                _logger.warning("Date range for %s limited to 1 year", field_name)
        except Exception as e:
            _logger.error("Error in _build_date_range for field %s: %s", field_name, e)
            # En cas d'erreur, générer une plage par défaut (3 derniers mois)
            min_date = date.today() - relativedelta(months=3)
            max_date = date.today()

        # Generate all intermediate dates based on interval
        date_values = []
        current_date = min_date

        if interval == 'day':
            delta = timedelta(days=1)
            format_str = '%Y-%m-%d'
        elif interval == 'week':
            delta = timedelta(weeks=1)
            # Use ISO week format
            format_str = 'W%W %Y'
        elif interval == 'month':
            # For months, use a relative delta
            delta = relativedelta(months=1)
            format_str = '%Y-%m'
        elif interval == 'quarter':
            delta = relativedelta(months=3)
            # Custom handling for quarters
            format_str = 'Q%q %Y'
        elif interval == 'year':
            delta = relativedelta(years=1)
            format_str = '%Y'
        else:
            # Default to month
            delta = relativedelta(months=1)
            format_str = '%Y-%m'

        while current_date <= max_date:
            # Format based on interval
            if interval == 'week':
                date_values.append(f"W{current_date.isocalendar()[1]} {current_date.year}")
            elif interval == 'quarter':
                quarter = (current_date.month - 1) // 3 + 1
                date_values.append(f"Q{quarter} {current_date.year}")
            else:
                date_values.append(current_date.strftime(format_str))

            # Move to next date
            current_date += delta

        return date_values

    def _generate_empty_combinations(self, model, group_by_list, domain, results):
        """Generate all combinations for fields with show_empty=True.
        Takes into account existing values for fields without show_empty.
        """
        # Split fields with and without show_empty
        show_empty_fields = []
        non_show_empty_fields = []
        all_values = {}

        # Identifier les champs qui ont des valeurs NULL/None dans les résultats existants
        # pour assurer la cohérence dans le traitement des valeurs NULL
        fields_with_nulls = set()

        for gb in group_by_list:
            field = gb.get('field')
            if not field:
                continue

            show_empty = gb.get('show_empty', False)
            interval = gb.get('interval')

            if show_empty and model._fields[field].type not in ['binary']:
                show_empty_fields.append((field, interval))

                if model._fields[field].type in ['date', 'datetime']:
                    # Approche plus robuste : utiliser les dates réelles des données existantes
                    # et y ajouter les dates récentes pour compléter
                    date_values = []

                    # 1. Utiliser notre propre requête SQL pour obtenir les dates min/max directement
                    # à partir de la base de données, indépendamment des résultats intermédiaires
                    try:
                        # Trouver les dates min et max réelles dans la base de données
                        min_max_query = f"""
                            SELECT 
                                MIN({field}::date) as min_date,
                                MAX({field}::date) as max_date
                            FROM {model._table}
                            WHERE {field} IS NOT NULL
                        """
                        request.env.cr.execute(min_max_query)
                        date_range = request.env.cr.fetchone()

                        if date_range and date_range[0] and date_range[1]:
                            db_min_date = date_range[0]  # Date minimum de la base
                            db_max_date = date_range[1]  # Date maximum de la base

                            # Filtrer les dates pour n'utiliser que celles qui ont réellement des données
                            # Cela corrige le problème où show_empty génère trop de dates intermédiaires
                            dates_with_data_query = f"""
                                SELECT DISTINCT
                                    EXTRACT(YEAR FROM {field}::date) as year,
                                    EXTRACT(MONTH FROM {field}::date) as month
                                FROM {model._table}
                                WHERE {field} IS NOT NULL
                                ORDER BY year, month
                            """
                            request.env.cr.execute(dates_with_data_query)
                            dates_with_data = request.env.cr.fetchall()
                            _logger.info("Found %s dates with data for field %s", len(dates_with_data), field)

                            # Utiliser les dates min/max de la base de données pour générer une plage complète
                            # C'est le comportement que l'utilisateur préfère

                            # Assurer que nous avons aussi quelques semaines récentes
                            today = date.today()
                            actual_max_date = max(db_max_date, today)

                            # 2. Générer toutes les valeurs selon l'intervalle
                            if interval == 'week':
                                # Convertir en début de semaine
                                week_min = db_min_date - timedelta(days=db_min_date.weekday())
                                week_max = actual_max_date + timedelta(days=(6 - actual_max_date.weekday()))

                                # Limiter à une année pour éviter les plages trop longues
                                if (week_max - week_min).days > 365:
                                    week_min = week_max - timedelta(days=365)

                                # Générer toutes les semaines complètes
                                current = week_min
                                while current <= week_max:
                                    week_str = f"W{current.isocalendar()[1]} {current.year}"
                                    date_values.append(week_str)
                                    current += timedelta(days=7)

                            elif interval == 'month':
                                # Convertir en début de mois
                                month_min = date(db_min_date.year, db_min_date.month, 1)
                                month_max = date(actual_max_date.year, actual_max_date.month, 1)

                                # Limiter à deux ans pour éviter les plages trop longues
                                if (month_max.year - month_min.year) * 12 + (month_max.month - month_min.month) > 24:
                                    month_min = date(month_max.year - 2, month_max.month, 1)

                                # Générer tous les mois
                                current = month_min
                                while current <= month_max:
                                    # Utiliser le format complet pour correspondre à ce que Odoo renvoie
                                    date_values.append(current.strftime('%B %Y'))
                                    current = (current.replace(day=28) + timedelta(days=4)).replace(
                                        day=1)  # Prochain mois

                            elif interval == 'quarter':
                                # Convertir en début de trimestre
                                q_min = db_min_date.month - 1
                                q_min = q_min - (q_min % 3)
                                quarter_min = date(db_min_date.year, q_min + 1 if q_min > 0 else 1, 1)

                                q_max = actual_max_date.month - 1
                                q_max = q_max - (q_max % 3)
                                quarter_max = date(actual_max_date.year, q_max + 1 if q_max > 0 else 1, 1)

                                # Générer tous les trimestres
                                current = quarter_min
                                while current <= quarter_max:
                                    quarter = ((current.month - 1) // 3) + 1
                                    date_values.append(f"Q{quarter} {current.year}")
                                    current = date(current.year + (1 if current.month > 9 else 0),
                                                   ((current.month - 1 + 3) % 12) + 1, 1)

                            elif interval == 'year':
                                for year in range(db_min_date.year, actual_max_date.year + 1):
                                    date_values.append(str(year))

                            else:  # day
                                # Pour les jours, limiter à 60 jours maximum
                                day_max = min(db_max_date, db_min_date + timedelta(days=60))
                                current = db_min_date
                                while current <= day_max:
                                    date_values.append(current.strftime('%d %b %Y'))
                                    current += timedelta(days=1)

                        else:
                            # Si pas de dates dans la BD, utiliser des dates récentes
                            existing_dates = set()
                            for r in results:
                                if field in r and r[field]:
                                    existing_dates.add(r[field])

                            for date_val in existing_dates:
                                if date_val:
                                    date_values.append(date_val)
                    except Exception as e:
                        _logger.error("Error generating date values: %s", e)
                        # En cas d'erreur, utiliser les dates des résultats
                        existing_dates = set()
                        for r in results:
                            if field in r and r[field]:
                                existing_dates.add(r[field])

                        for date_val in existing_dates:
                            if date_val:
                                date_values.append(date_val)

                    # 3. Si on n'a toujours pas assez de dates, ajouter des dates récentes
                    if len(date_values) < 3:
                        today = date.today()

                        if interval == 'day':
                            # Formatter les dates exactement comme Odoo
                            for i in range(7):
                                dt = today - timedelta(days=i)
                                formatted = dt.strftime('%d %b %Y')  # Format: '11 Apr 2025'
                                if formatted not in date_values:
                                    date_values.append(formatted)
                        elif interval == 'week':
                            for i in range(4):
                                week_date = today - timedelta(weeks=i)
                                formatted = f"W{week_date.isocalendar()[1]} {week_date.year}"
                                if formatted not in date_values:
                                    date_values.append(formatted)
                        elif interval == 'month':
                            for i in range(6):
                                month_date = today - relativedelta(months=i)
                                formatted = month_date.strftime('%B %Y')  # Format: 'April 2025'
                                if formatted not in date_values:
                                    date_values.append(formatted)
                        elif interval == 'quarter':
                            for i in range(4):
                                quarter_date = today - relativedelta(months=i * 3)
                                quarter = (quarter_date.month - 1) // 3 + 1
                                formatted = f"Q{quarter} {quarter_date.year}"
                                if formatted not in date_values:
                                    date_values.append(formatted)
                        elif interval == 'year':
                            for i in range(3):
                                formatted = str(today.year - i)
                                if formatted not in date_values:
                                    date_values.append(formatted)

                    # Utiliser cette plage fixe
                    all_values[(field, interval)] = date_values
                else:
                    # Pour tous les autres types de champs
                    all_values[(field, interval)] = self._get_field_values(model, field, domain)
            else:
                non_show_empty_fields.append((field, interval))

        if not show_empty_fields:
            return []

        # For fields without show_empty, use only values that exist in results
        existing_values = {}
        for field, interval in non_show_empty_fields:
            field_with_interval = f"{field}:{interval}" if interval else field
            values = set()
            for result in results:
                val = result.get(field_with_interval)
                if val is not None:
                    values.add(val)
            existing_values[(field, interval)] = list(values)

        # Prepare for all combinations
        all_fields = non_show_empty_fields + show_empty_fields
        all_fields_values = []
        all_field_names = []

        for field, interval in all_fields:
            if (field, interval) in existing_values:
                # Field without show_empty - use existing values
                values = existing_values[(field, interval)]
            else:
                # Field with show_empty - use all possible values
                values = all_values[(field, interval)]

            if values:  # Only add if there are values
                all_fields_values.append(values)
                all_field_names.append(field)

        if not all_fields_values:
            return []

        # Générer toutes les combinaisons valides
        # TOUJOURS utiliser des dictionnaires pour la cohérence des retours
        if len(all_fields_values) == 1 and len(all_field_names) == 1:
            # Cas spécial : un seul champ
            field_name = all_field_names[0]
            return [{field_name: value} for value in all_fields_values[0]]
        elif len(all_fields_values) >= 1:
            # Cas normal : plusieurs champs ou combinaisons
            combinations = list(itertools.product(*all_fields_values))
            return [dict(zip(all_field_names, combo)) for combo in combinations]
        else:
            # Cas où aucune valeur n'est trouvée
            return []

    def _handle_show_empty(self, results, model, group_by_list, domain, measures=None):
        """Handle show_empty for groupBy fields by filling in missing combinations."""
        if not any(gb.get('show_empty', False) for gb in group_by_list):
            return results  # No show_empty, return original results

        # Generate all possible combinations for show_empty fields
        all_combinations = self._generate_empty_combinations(model, group_by_list, domain, results)
        if not all_combinations:
            return results

        # Create a dictionary for easy lookup of existing results
        existing_results = {}
        for result in results:
            # Create a key based on groupby field values
            key_parts = []
            for gb in group_by_list:
                field = gb.get('field')
                interval = gb.get('interval')
                if field:
                    field_with_interval = f"{field}:{interval}" if interval else field
                    value = result.get(field_with_interval)

                    # Format the value in a consistent way
                    if isinstance(value, tuple) and len(value) == 2:
                        # Extract the ID for consistent lookup
                        formatted_value = value[0]
                    elif isinstance(value, dict) and 'id' in value:
                        # Extract the ID for consistent lookup
                        formatted_value = value['id']
                    else:
                        formatted_value = value

                    key_parts.append(str(formatted_value))

            existing_results[tuple(key_parts)] = result

        # Create combined results with empty values for missing combinations
        combined_results = []

        for combo in all_combinations:
            # Create a key to check if this combination exists in results
            key_parts = []
            skip_combo = False

            # S'assurer que combo est toujours un dictionnaire à ce stade
            if not isinstance(combo, dict):
                _logger.error("Unexpected non-dict combo in _handle_show_empty: %s", combo)
                continue

            for gb in group_by_list:
                field = gb.get('field')
                if field:
                    value = combo.get(field, '')

                    # Skip combinations with None values for date fields that don't have show_empty
                    if value is None and not gb.get('show_empty', False):
                        skip_combo = True
                        break

                    # Format the value in a consistent way
                    if isinstance(value, tuple) and len(value) == 2:
                        # Extract the ID for consistent lookup
                        formatted_value = value[0]
                    elif isinstance(value, dict) and 'id' in value:
                        # Extract the ID for consistent lookup
                        formatted_value = value['id']
                    else:
                        formatted_value = value

                    key_parts.append(str(formatted_value))

            # Skip this combination if it has None values for non-show_empty fields
            if skip_combo:
                continue

            # S'assurer que la clé ne contient pas "None" comme valeur textuelle
            # car ça crée des entrées indésirables
            if "None" in key_parts:
                continue

            combo_key = tuple(key_parts)

            if combo_key in existing_results:
                # Use existing result
                combined_results.append(existing_results[combo_key])
            else:
                # Create new empty result with correct structure
                new_result = {}

                # Add all accumulated measures with default values
                for measure in measures or []:
                    field = measure.get('field')
                    agg = measure.get('aggregation')
                    # Set default value (0 for numeric fields, False for others)
                    new_result[field] = 0 if model._fields[field].type in ['float', 'monetary', 'integer'] else False

                # Add combination values to result, avec les formats compatibles read_group
                for gb in group_by_list:
                    field = gb.get('field')
                    interval = gb.get('interval')

                    if field in combo:
                        # Ajouter à la fois le champ original et le champ avec intervalle
                        # pour assurer la compatibilité avec _transform_graph_data
                        new_result[field] = combo[field]

                        # Ajouter également avec le format field:interval pour assurer la compatibilité
                        if interval:
                            field_with_interval = f"{field}:{interval}"
                            new_result[field_with_interval] = combo[field]

                combined_results.append(new_result)

        return combined_results

    def _process_block(self, model, domain, config):
        """Process block type visualization."""
        block_options = config.get('block_options', {})
        field = block_options.get('field')
        aggregation = block_options.get('aggregation', 'sum')
        label = block_options.get('label', field)

        if not field:
            return {'error': 'Missing field in block_options'}

        # Compute the aggregated value
        if aggregation == 'count':
            count = model.search_count(domain)
            return {
                'data': {
                    'value': count,
                    'label': label or 'Count',
                    'odash.domain': []
                }
            }
        else:
            # For sum, avg, min, max
            try:
                # Use SQL for better performance on large datasets
                agg_func = aggregation.upper()

                # Construit la clause WHERE et les paramètres de façon sécurisée
                if not domain:
                    where_clause = "TRUE"
                    where_params = []
                else:
                    # Au lieu d'utiliser _where_calc directement, utilisons search pour obtenir la requête
                    # C'est une façon plus sûre et robuste de générer la clause WHERE
                    records = model.search(domain)
                    if not records:
                        where_clause = "FALSE"  # Aucun enregistrement correspondant
                        where_params = []
                    else:
                        id_list = records.ids
                        where_clause = f"{model._table}.id IN %s"
                        where_params = [tuple(id_list) if len(id_list) > 1 else (id_list[0],)]

                # Solution plus fiable et unifiée pour toutes les agrégations
                try:
                    _logger.info("Processing %s aggregation for field %s", agg_func, field)

                    # Vérifier d'abord s'il y a des enregistrements
                    count_query = f"""
                        SELECT COUNT(*) as count
                        FROM {model._table}
                        WHERE {where_clause}
                    """
                    request.env.cr.execute(count_query, where_params)
                    count_result = request.env.cr.fetchone()
                    count = 0
                    if count_result and len(count_result) > 0:
                        count = count_result[0] if count_result[0] is not None else 0

                    _logger.info("Found %s records matching the criteria", count)

                    # Si aucun enregistrement, renvoyer 0 pour toutes les agrégations
                    if count == 0:
                        value = 0
                        _logger.info("No records found, using default value 0")
                    else:
                        # Calculer l'agrégation selon le type
                        if agg_func == 'AVG':
                            # Calculer la somme pour la moyenne
                            sum_query = f"""
                                SELECT SUM({field}) as total
                                FROM {model._table}
                                WHERE {where_clause}
                            """
                            request.env.cr.execute(sum_query, where_params)
                            sum_result = request.env.cr.fetchone()
                            total = 0

                            if sum_result and len(sum_result) > 0:
                                total = sum_result[0] if sum_result[0] is not None else 0

                            # Calculer la moyenne
                            value = total / count if count > 0 else 0
                            _logger.info("Calculated AVG manually: total=%s, count=%s, avg=%s", total, count, value)
                        elif agg_func == 'MAX':
                            # Calculer le maximum
                            max_query = f"""
                                SELECT {field} as max_value
                                FROM {model._table}
                                WHERE {where_clause} AND {field} IS NOT NULL
                                ORDER BY {field} DESC
                                LIMIT 1
                            """
                            request.env.cr.execute(max_query, where_params)
                            max_result = request.env.cr.fetchone()
                            value = 0

                            if max_result and len(max_result) > 0:
                                value = max_result[0] if max_result[0] is not None else 0

                            _logger.info("Calculated MAX manually: %s", value)
                        elif agg_func == 'MIN':
                            # Calculer le minimum
                            min_query = f"""
                                SELECT {field} as min_value
                                FROM {model._table}
                                WHERE {where_clause} AND {field} IS NOT NULL
                                ORDER BY {field} ASC
                                LIMIT 1
                            """
                            request.env.cr.execute(min_query, where_params)
                            min_result = request.env.cr.fetchone()
                            value = 0

                            if min_result and len(min_result) > 0:
                                value = min_result[0] if min_result[0] is not None else 0

                            _logger.info("Calculated MIN manually: %s", value)
                        elif agg_func == 'SUM':
                            # Calculer la somme
                            sum_query = f"""
                                SELECT SUM({field}) as total
                                FROM {model._table}
                                WHERE {where_clause}
                            """
                            request.env.cr.execute(sum_query, where_params)
                            sum_result = request.env.cr.fetchone()
                            value = 0

                            if sum_result and len(sum_result) > 0:
                                value = sum_result[0] if sum_result[0] is not None else 0

                            _logger.info("Calculated SUM manually: %s", value)
                        else:
                            # Fonction d'agrégation non reconnue
                            value = 0
                            _logger.warning("Unrecognized aggregation function: %s", agg_func)
                except Exception as e:
                    _logger.exception("Error calculating %s for %s: %s", agg_func, field, e)
                    value = 0

                return {
                    'data': {
                        'value': value,
                        'label': label or f'{aggregation.capitalize()} of {field}',
                        'odash.domain': []
                    }
                }
            except Exception as e:
                _logger.error("Error calculating block value: %s", e)
                return {'error': f'Error calculating {aggregation} for {field}: {str(e)}'}

    def _process_graph(self, model, domain, group_by_list, order_string, config):
        """Process graph type visualization."""
        graph_options = config.get('graph_options', {})
        measures = graph_options.get('measures', [])

        if not group_by_list:
            group_by_list = [{'field': 'name'}]
            order_string = "name asc"

        if not measures:
            # Default to count measure if not specified
            measures = [{'field': 'id', 'aggregation': 'count'}]

        # Prepare groupby fields for read_group
        groupby_fields = []

        for gb in group_by_list:
            field = gb.get('field')
            interval = gb.get('interval')
            if field:
                groupby_fields.append(f"{field}:{interval}" if interval else field)

        # Prepare measure fields for read_group
        measure_fields = []
        for measure in measures:
            measure_fields.append(f"{measure.get('field')}:{measure.get('aggregation', 'sum')}")

        # Execute read_group
        try:
            results = model.read_group(
                domain,
                fields=measure_fields,
                groupby=groupby_fields,
                orderby=order_string,
                lazy=False
            )

            # Handle show_empty if needed
            has_show_empty = any(gb.get('show_empty', False) for gb in group_by_list)
            if has_show_empty:
                results = self._handle_show_empty(results, model, group_by_list, domain, measures)

            # Transform results into the expected format
            transformed_data = []
            for result in results:
                data = {
                    'key': result[groupby_fields[0]],
                    'odash.domain': result['__domain']
                }

                if len(groupby_fields) > 1:
                    sub_results = model.read_group(
                        result['__domain'],
                        fields=measure_fields,
                        groupby=groupby_fields[1],
                        orderby=groupby_fields[1],
                        lazy=True
                    )

                    for sub_result in sub_results:
                        for measure in config['graph_options']['measures']:
                            data[f"{measure['field']}|{sub_result[groupby_fields[1]]}"] = sub_result[measure['field']]
                else:
                    for measure in config['graph_options']['measures']:
                        data[measure['field']] = result[measure['field']]

                transformed_data.append(data)

            return {'data': transformed_data}

        except Exception as e:
            _logger.exception("Error in _process_graph: %s", e)
            return {'error': f'Error processing graph data: {str(e)}'}

    def _process_table(self, model, domain, group_by_list, order_string, config):
        """Process table type visualization."""
        table_options = config.get('table_options', {})
        columns = table_options.get('columns', [])
        limit = table_options.get('limit', 50)
        offset = table_options.get('offset', 0)

        if not columns:
            return {'error': 'Missing columns configuration for table'}

        # Extract fields to read
        fields_to_read = [col.get('field') for col in columns if col.get('field')]

        # Check if grouping is required
        if group_by_list:
            # Table with grouping - use read_group
            groupby_fields = []
            has_show_empty = any(gb.get('show_empty', False) for gb in group_by_list)

            for gb in group_by_list:
                field = gb.get('field')
                interval = gb.get('interval')
                if field:
                    groupby_fields.append(f"{field}:{interval}" if interval else field)
                    if field not in fields_to_read:
                        fields_to_read.append(field)

            if not groupby_fields:
                return {'error': "Invalid 'groupBy' configuration for grouped table"}

            # Add __count field for the counts per group
            fields_to_read.append('__count')

            try:
                # Execute read_group
                results = model.read_group(
                    domain,
                    fields=fields_to_read,
                    groupby=groupby_fields,
                    orderby=order_string,
                    lazy=False
                )

                # Handle show_empty if needed
                if has_show_empty:
                    results = self._handle_show_empty(results, model, group_by_list, domain)

                # Format for table display
                total_count = len(results)
                results = results[offset:offset + limit] if limit else results

                # Add domain for each row and map aggregation fields to their specified columns
                for result in results:

                    for fields in fields_to_read:
                        if isinstance(result.get(fields, False), tuple) and len(result.get(fields)) > 1:
                            result[field] = result[field][1]

                    # Map aggregation values based on column configuration
                    if '__count' in result:
                        for column in table_options['columns']:
                            if column.get('aggregation', False) == 'count':
                                result[column.get('field')] = result['__count']
                                del result['__count']

                    if '__domain' in result:
                        result['odash.domain'] = result['__domain']
                        del result['__domain']
                    else:
                        row_domain = []  # Démarrer avec un domaine vide, sans inclure le domaine d'entrée

                        # Add domain elements for each groupby field
                        for gb_field in groupby_fields:
                            base_field = gb_field.split(':')[0] if ':' in gb_field else gb_field
                            value = result.get(gb_field)

                            if value is not None:
                                if gb_field.endswith(':month') or gb_field.endswith(':week') or gb_field.endswith(
                                        ':day') or gb_field.endswith(':year'):
                                    # Handle date intervals
                                    base_field = gb_field.split(':')[0]
                                    interval = gb_field.split(':')[1]

                                    # Parse the date and build a range domain
                                    date_start, date_end = self._parse_date_from_string(str(value), return_range=True)
                                    if date_start and date_end:
                                        row_domain.append([base_field, '>=', date_start.isoformat()])
                                        row_domain.append([base_field, '<=', date_end.isoformat()])
                                else:
                                    # Direct comparison for regular fields
                                    row_domain.append([base_field, '=', value])

                        result['odash.domain'] = row_domain

                return {
                    'data': results,
                    'metadata': {
                        'page': offset // limit + 1 if limit else 1,
                        'limit': limit,
                        'total_count': total_count
                    }
                }

            except Exception as e:
                _logger.exception("Error in _process_table with groupBy: %s", e)
                return {'error': f'Error processing grouped table: {str(e)}'}

        else:
            # Simple table - use search_read
            try:
                # Count total records for pagination
                total_count = model.search_count(domain)

                # Fetch the records
                records = model.search_read(
                    domain,
                    fields=fields_to_read,
                    limit=limit,
                    offset=offset,
                    order=order_string
                )

                # Add domain for each record - uniquement l'ID, sans le domaine d'entrée
                for record in records:
                    for key in record.keys():
                        if isinstance(record[key], tuple):
                            record[key] = record[key][1]
                    record['odash.domain'] = [('id', '=', record['id'])]

                return {
                    'data': records,
                    'metadata': {
                        'page': offset // limit + 1 if limit else 1,
                        'limit': limit,
                        'total_count': total_count
                    }
                }

            except Exception as e:
                _logger.exception("Error in _process_table: %s", e)
                return {'error': f'Error processing table: {str(e)}'}

    def _process_sql_request(self, sql_request, viz_type, config):
        """Process a SQL request with security measures."""
        try:
            request.env.cr.execute(sql_request)
            results = request.env.cr.dictfetchall()

            # Format data based on visualization type
            if viz_type == 'graph':
                if results and isinstance(results[0], dict) and 'key' not in results[0]:
                    transformed_results = []
                    for row in results:
                        if isinstance(row, dict) and row:
                            new_row = {}
                            keys = list(row.keys())
                            if keys:
                                first_key = keys[0]
                                new_row['key'] = row[first_key]

                                for k in keys[1:]:
                                    new_row[k] = row[k]

                                transformed_results.append(new_row)
                            else:
                                transformed_results.append(row)
                        else:
                            transformed_results.append(row)
                    return {'data': transformed_results}
                else:
                    return {'data': results}
            elif viz_type == 'table':
                return {'data': results}
            elif viz_type == 'block':
                results = results[0]
                results["label"] = config.get('block_options').get('field')
                return {'data': results}

        except Exception as e:
            _logger.error("SQL execution error: %s", e)
            return {'error': f'SQL error: {str(e)}'}

        return {'error': 'Unexpected error in SQL processing'}
