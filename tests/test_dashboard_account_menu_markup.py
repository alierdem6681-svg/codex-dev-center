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
