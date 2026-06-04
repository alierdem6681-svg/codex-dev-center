import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DashboardAccountMenuMarkupTest(unittest.TestCase):
    def test_dashboard_account_menu_uses_auth_state_and_logout_endpoint(self):
        html = (ROOT / "web_panel" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="accountMenuButton"', html)
        self.assertIn('aria-haspopup="true"', html)
        self.assertIn('aria-controls="accountMenuPanel"', html)
        self.assertIn('role="menu"', html)
        self.assertGreaterEqual(html.count('role="menuitem"'), 3)
        self.assertIn("data?.auth?.username", html)
        self.assertIn("Profil", html)
        self.assertIn("Hesap ayarları", html)
        self.assertIn("'/api/auth/logout'", html)
        self.assertIn("event.key === 'Escape'", html)


if __name__ == "__main__":
    unittest.main()
