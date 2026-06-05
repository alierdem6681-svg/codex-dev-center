import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DashboardAccountMenuMarkupTest(unittest.TestCase):
    def test_dashboard_direct_access_has_no_account_menu_or_logout(self):
        html = (ROOT / "web_panel" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertNotIn('id="accountMenu"', html)
        self.assertNotIn('id="accountMenuButton"', html)
        self.assertNotIn('aria-controls="accountMenuPanel"', html)
        self.assertNotIn("data?.auth?.username", html)
        self.assertNotIn("'/api/auth/logout'", html)
        self.assertNotIn("location.href = '/login'", html)
        self.assertNotIn("Çıkış", html)

    def test_dashboard_login_compat_page_redirects_without_credentials(self):
        html = (ROOT / "web_panel" / "static" / "login.html").read_text(encoding="utf-8")

        self.assertIn("Dashboard açılıyor", html)
        self.assertIn("Panel doğrudan açılır", html)
        self.assertIn("location.replace('/')", html)
        self.assertNotIn("Kullanıcı adı", html)
        self.assertNotIn("Şifre", html)
        self.assertNotIn("/api/auth/login", html)

    def test_panel_server_direct_access_does_not_require_session_cookie(self):
        server = (ROOT / "web_panel" / "panel_server.py").read_text(encoding="utf-8")

        self.assertIn("def authorized", server)
        self.assertIn("return True", server)
        self.assertIn('{"Location": "/"}', server)
        self.assertNotIn('"error": "unauthorized"', server)
        self.assertNotIn('{"Location": "/login"}', server)

    def test_panel_server_public_post_surface_is_read_only(self):
        server = (ROOT / "web_panel" / "panel_server.py").read_text(encoding="utf-8")

        self.assertIn('"error": "dashboard_direct_access_read_only"', server)
        self.assertIn('"production_deploy_allowed": False', server)
        self.assertIn('"critical_operations_allowed": False', server)
        self.assertNotIn('action == "production_deploy_start"', server)
        self.assertNotIn('action == "cto_doctor_fix"', server)
        self.assertNotIn('action == "staging_deploy"', server)

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

    def test_dashboard_uses_neutral_shell_without_background_image(self):
        html = (ROOT / "web_panel" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertNotIn("/assets/dashboard-landscape.png", html)
        self.assertNotIn("url('/assets/", html)
        self.assertFalse((ROOT / "web_panel" / "static" / "assets" / "dashboard-landscape.png").exists())
        self.assertIn('class="dashboard-shell"', html)
        self.assertIn('class="sidebar"', html)
        self.assertIn('id="metricActiveQueue"', html)
        self.assertIn('id="metricWorkers"', html)

    def test_dashboard_task_list_filters_history_tasks_and_keeps_running_first(self):
        html = (ROOT / "web_panel" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="showLiveTasks"', html)
        self.assertIn("Geçmiş/canlı kayıtları göster", html)
        self.assertIn("function taskIsLive(t)", html)
        self.assertIn("t.deployment_status || t.deploymentStatus || t.delivery_level", html)
        self.assertIn("function taskIsHistorical(t){ return taskIsLive(t) || taskIsClosed(t); }", html)
        self.assertIn("function taskIsRunning(t){ return taskStatus(t) === 'RUNNING'; }", html)
        self.assertIn("if (taskIsRunning(a) !== taskIsRunning(b))", html)
        self.assertIn("list = list.filter(t => !taskIsHistorical(t));", html)
        self.assertIn("const visibleBeforeFilters = showLiveTasks.checked ? tasks() : tasks().filter(t => !taskIsHistorical(t));", html)
        self.assertIn("Güncel görev yok.", html)
        self.assertIn("Filtreye uyan görev yok.", html)
        self.assertIn('class="empty-state"', html)
        self.assertIn("list.sort(compareTasks);", html)
        self.assertIn("function setFilterOptions(selectEl, defaultLabel, values)", html)
        self.assertIn("selectEl.dataset.optionsHtml !== html", html)
        self.assertIn("[statusFilter, workerFilter, riskFilter, sortMode, showLiveTasks]", html)
        self.assertIn("el.addEventListener('change', event =>", html)


if __name__ == "__main__":
    unittest.main()
