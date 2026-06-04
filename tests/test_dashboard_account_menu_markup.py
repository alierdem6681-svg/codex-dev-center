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
        self.assertGreaterEqual(html.count('role="menuitem"'), 2)
        self.assertIn("data?.auth?.username", html)
        self.assertIn("Hesap ayarları", html)
        self.assertIn("'/api/auth/logout'", html)
        self.assertIn("event.key === 'Escape'", html)

    def test_dashboard_cleanup_removes_operational_sections(self):
        html = (ROOT / "web_panel" / "static" / "index.html").read_text(encoding="utf-8")

        removed_labels = [
            "Raporlar",
            "Son Hata ve Çözüm Önerisi",
            "GitHub Senkronizasyonu",
            "Profil",
            "Son Kontroller",
            "Kalite Kapıları",
            "Deploy Komutları",
            "Pipeline Gözlemi",
            "Production Pipeline",
            "Operasyonel Akış",
            "Canlıya Alma Durumu",
            "Ön Canlı Sonucu",
            "Geri Alma Sonucu",
            "Görev Kuyruğu",
            "Çalışan / Görev Kuyruğu / Toparlama",
        ]
        for label in removed_labels:
            self.assertNotIn(label, html)

        self.assertIn("Pipeline Flow", html)
        self.assertIn("Görevler", html)
        self.assertIn("Ayarlar", html)


if __name__ == "__main__":
    unittest.main()
