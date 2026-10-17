"""Shared typography loads on white app modules, never protected Finance."""
from pathlib import Path
import unittest
from flask import Blueprint,Flask,render_template


class TypographyScopeTests(unittest.TestCase):
    def test_finance_blueprint_and_finance_shell_exclude_the_new_sheet(self):
        root=Path(__file__).resolve().parents[1]
        app=Flask(__name__,template_folder=str(root/'templates'),static_folder=str(root/'static'))
        finance=Blueprint('finance',__name__)
        @finance.get('/finance')
        def finance_page():return render_template('_premium_styles.html',finance_ui={'enabled':False})
        app.register_blueprint(finance)
        products=Blueprint('products',__name__)
        @products.get('/finance-entry')
        def finance_entry():return render_template('_premium_styles.html',finance_ui=None)
        app.register_blueprint(products)
        @app.get('/finance-shell')
        def finance_shell():return render_template('_premium_styles.html',finance_ui={'enabled':True})
        @app.get('/app')
        def app_page():return render_template('_premium_styles.html',finance_ui=None)
        client=app.test_client()
        for path in ('/finance','/finance-shell','/finance-entry'):
            response=client.get(path);self.assertEqual(response.status_code,200)
            self.assertNotIn('kilas_typography.css',response.text)
        self.assertIn('kilas_premium_finance.css',client.get('/finance').text)
        self.assertIn('kilas_typography.css',client.get('/app').text)


if __name__=='__main__':unittest.main()
