# -*- coding: utf-8 -*-
"""
Test exec() Security for Odashboard Module

This test ensures that the restricted namespace prevents dangerous operations.
"""

from odoo.tests import TransactionCase


class TestExecSecurity(TransactionCase):
    """Test that exec() uses a restricted namespace"""

    def setUp(self):
        super(TestExecSecurity, self).setUp()
        self.engine_model = self.env['odash.engine']
        self.engine = self.engine_model._get_single_record()

    def test_safe_globals_no_import(self):
        """Test that __import__ is not available in safe globals"""
        safe_globals = self.engine._get_safe_globals()
        
        # __import__ should not be in __builtins__
        self.assertNotIn('__import__', safe_globals.get('__builtins__', {}))

    def test_safe_globals_no_open(self):
        """Test that open() is not available in safe globals"""
        safe_globals = self.engine._get_safe_globals()
        
        # open should not be in __builtins__
        self.assertNotIn('open', safe_globals.get('__builtins__', {}))

    def test_safe_globals_no_eval(self):
        """Test that eval() is not available in safe globals"""
        safe_globals = self.engine._get_safe_globals()
        
        # eval should not be in __builtins__
        self.assertNotIn('eval', safe_globals.get('__builtins__', {}))

    def test_safe_globals_no_exec(self):
        """Test that exec() is not available in safe globals"""
        safe_globals = self.engine._get_safe_globals()
        
        # exec should not be in __builtins__
        self.assertNotIn('exec', safe_globals.get('__builtins__', {}))

    def test_safe_globals_no_compile(self):
        """Test that compile() is not available in safe globals"""
        safe_globals = self.engine._get_safe_globals()
        
        # compile should not be in __builtins__
        self.assertNotIn('compile', safe_globals.get('__builtins__', {}))

    def test_safe_globals_has_safe_builtins(self):
        """Test that safe built-ins are available"""
        safe_globals = self.engine._get_safe_globals()
        builtins = safe_globals.get('__builtins__', {})
        
        # These should be available
        safe_builtins = ['str', 'int', 'float', 'bool', 'list', 'dict', 'len', 'range']
        for builtin in safe_builtins:
            self.assertIn(builtin, builtins)

    def test_safe_globals_has_required_modules(self):
        """Test that required modules are available"""
        safe_globals = self.engine._get_safe_globals()
        
        # These modules should be available
        required_modules = ['logging', 'datetime', 'timedelta', 'relativedelta', 'pytz']
        for module in required_modules:
            self.assertIn(module, safe_globals)

    def test_malicious_code_import_blocked(self):
        """Test that malicious code trying to import os is blocked"""
        malicious_code = """
def malicious_function():
    import os
    return os.system('echo hacked')
"""
        
        # Store the malicious code
        self.engine.write({'code': malicious_code})
        
        # Try to execute it - should fail because import is not available
        result = self.engine._execute_engine_code('malicious_function')
        
        # Should return an error
        self.assertIsInstance(result, dict)
        self.assertIn('error', result)

    def test_malicious_code_open_blocked(self):
        """Test that malicious code trying to open files is blocked"""
        malicious_code = """
def read_passwd():
    with open('/etc/passwd', 'r') as f:
        return f.read()
"""
        
        # Store the malicious code
        self.engine.write({'code': malicious_code})
        
        # Try to execute it - should fail because open is not available
        result = self.engine._execute_engine_code('read_passwd')
        
        # Should return an error
        self.assertIsInstance(result, dict)
        self.assertIn('error', result)

    def test_malicious_code_builtins_access_blocked(self):
        """Test that accessing __builtins__.__import__ is blocked"""
        malicious_code = """
def import_via_builtins():
    import_func = __builtins__['__import__']
    os = import_func('os')
    return os.system('echo hacked')
"""
        
        # Store the malicious code
        self.engine.write({'code': malicious_code})
        
        # Try to execute it - should fail
        result = self.engine._execute_engine_code('import_via_builtins')
        
        # Should return an error
        self.assertIsInstance(result, dict)
        self.assertIn('error', result)

    def test_safe_code_execution_works(self):
        """Test that safe code still executes properly"""
        safe_code = """
def safe_function(a, b):
    return a + b
"""
        
        # Store the safe code
        self.engine.write({'code': safe_code})
        
        # Execute it - should work
        result = self.engine._execute_engine_code('safe_function', 2, 3)
        
        # Should return 5
        self.assertEqual(result, 5)

    def test_safe_code_with_logging_works(self):
        """Test that safe code using logging module works"""
        safe_code = """
import logging
_logger = logging.getLogger(__name__)

def log_something(message):
    _logger.info(message)
    return True
"""
        
        # Store the safe code
        self.engine.write({'code': safe_code})
        
        # Execute it - should work
        result = self.engine._execute_engine_code('log_something', 'Test message')
        
        # Should return True
        self.assertTrue(result)
