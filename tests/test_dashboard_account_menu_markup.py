import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DashboardAccountMenuMarkupTest(unittest.TestCase):
    def test_dashboard_shell_has_no_membership_menu(self):
        html = (ROOT / "web_panel" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertNotIn('id="accountMenuButton"', html)
        self.assertNotIn('id="accountMenuPanel"', html)
        self.assertNotIn("data?.auth?.username", html)
        self.assertNotIn("'/api/auth/logout'", html)
        self.assertNotIn("location.href = '/login'", html)

    def test_panel_server_uses_direct_access_contract(self):
        source = (ROOT / "web_panel" / "panel_server.py").read_text(encoding="utf-8")

        self.assertIn("def public_panel_auth_state", source)
        self.assertIn('"auth_mode": "disabled"', source)
        self.assertIn('"membership_enabled": False', source)
        self.assertIn("self.redirect_dashboard()", source)
        self.assertIn('"error": "auth_disabled"', source)
        self.assertIn('"error": "post_actions_disabled"', source)
        self.assertNotIn("redirect_login", source)

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
            "Ayarlar",
            "Son İşlem",
            "Hesap ayarları",
            "Güncellendi",
            "Salt okunur",
            "Seçili stage",
            "Stage durumu",
            "Toplam görev",
            "Blok / hata",
            "Status dağılımı",
            "flow-progress",
            "pipelineFlowUpdated",
            "settingsBadges",
        ]
        for label in removed_labels:
            self.assertNotIn(label, html)

        self.assertIn("Pipeline Flow", html)
        self.assertIn("Görevler", html)

    def test_dashboard_uses_scenic_shell_design(self):
        html = (ROOT / "web_panel" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn("/assets/dashboard-landscape.png", html)
        self.assertIn('class="dashboard-shell"', html)
        self.assertIn('class="sidebar"', html)
        self.assertIn('id="metricActiveQueue"', html)
        self.assertIn('id="metricWorkers"', html)

    def test_dashboard_task_list_filters_live_tasks_and_keeps_running_first(self):
        html = (ROOT / "web_panel" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="showLiveTasks"', html)
        self.assertIn("Canlıya alınanları göster", html)
        self.assertIn("function taskIsLive(t)", html)
        self.assertIn("t.deployment_status || t.deploymentStatus || t.delivery_level", html)
        self.assertIn("function taskIsRunning(t){ return taskStatus(t) === 'RUNNING'; }", html)
        self.assertIn("if (taskIsRunning(a) !== taskIsRunning(b))", html)
        self.assertIn("list = list.filter(t => !taskIsLive(t));", html)
        self.assertIn("list.sort(compareTasks);", html)
        self.assertIn("function setFilterOptions(selectEl, defaultLabel, values)", html)
        self.assertIn("selectEl.dataset.optionsHtml !== html", html)
        self.assertIn("[statusFilter, workerFilter, riskFilter, sortMode, showLiveTasks]", html)
        self.assertIn("el.addEventListener('change', event =>", html)


if __name__ == "__main__":
    unittest.main()
