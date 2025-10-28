# -*- coding: utf-8 -*-
"""
Test RPC Security for Odashboard Module

This test ensures that private methods cannot be called via RPC.
"""

from odoo.tests import TransactionCase
from odoo.exceptions import AccessError


class TestRPCSecurity(TransactionCase):
    """Test that private methods are not accessible via RPC"""

    def setUp(self):
        super(TestRPCSecurity, self).setUp()
        self.engine_model = self.env['odash.engine']
        self.engine = self.engine_model._get_single_record()

    def test_private_execute_engine_code_not_callable(self):
        """Test that _execute_engine_code is private and not callable via RPC"""
        # Private methods starting with _ should exist
        self.assertTrue(hasattr(self.engine, '_execute_engine_code'))
        
        # But public version should not exist
        self.assertFalse(hasattr(self.engine, 'execute_engine_code'))

    def test_private_execute_unified_request_not_callable(self):
        """Test that _execute_unified_request is private and not callable via RPC"""
        # Private methods starting with _ should exist
        self.assertTrue(hasattr(self.engine, '_execute_unified_request'))
        
        # But public version should not exist
        self.assertFalse(hasattr(self.engine, 'execute_unified_request'))

    def test_private_method_can_be_called_internally(self):
        """Test that private methods can still be called internally"""
        # This should work when called from within the module
        result = self.engine._execute_unified_request(
            'get_models',
            {},
            self.env
        )
        
        # Should return a valid result
        self.assertIsInstance(result, dict)
        self.assertIn('success', result)

    def test_public_methods_do_not_exist(self):
        """Test that no public execute methods exist"""
        # Get all public methods (not starting with _)
        public_methods = [
            method for method in dir(self.engine)
            if not method.startswith('_') and callable(getattr(self.engine, method))
        ]
        
        # Ensure execute_engine_code and execute_unified_request are not in public methods
        self.assertNotIn('execute_engine_code', public_methods)
        self.assertNotIn('execute_unified_request', public_methods)

    def test_rpc_attack_simulation(self):
        """Simulate an RPC attack trying to call private methods"""
        # Try to get the public method (should not exist)
        with self.assertRaises(AttributeError):
            getattr(self.engine, 'execute_engine_code')
        
        with self.assertRaises(AttributeError):
            getattr(self.engine, 'execute_unified_request')
