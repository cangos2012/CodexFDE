from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PageElements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = {}
        self.tags = []
        self.assets = []
        self.duplicates = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if 'id' in attrs:
            if attrs['id'] in self.ids:
                self.duplicates.append(attrs['id'])
            self.ids[attrs['id']] = (tag, attrs)
        if tag == 'script' and attrs.get('src'):
            self.assets.append(attrs['src'])
        if tag == 'link' and attrs.get('rel') == 'stylesheet':
            self.assets.append(attrs['href'])


class HarnessWebDashboardTests(unittest.TestCase):
    """Artifact contract; live browser behavior is covered by the Node UI tests."""

    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / 'harness_web/index.html').read_text(encoding='utf-8')
        cls.script = (ROOT / 'harness_web/app.js').read_text(encoding='utf-8')
        cls.styles = (ROOT / 'harness_web/styles.css').read_text(encoding='utf-8')
        cls.page = PageElements()
        cls.page.feed(cls.html)

    def test_one_verified_upstream_entry_replaces_the_second_write_workspace(self):
        tag, attrs = self.page.ids['workbench-link']
        self.assertEqual('a', tag)
        self.assertIn('hidden', attrs)
        self.assertNotIn('href', attrs)  # Not guessed before the proxy health read.
        self.assertEqual('_blank', attrs['target'])
        self.assertIn('noopener', attrs['rel'])
        self.assertIn('health.value.workbench_url', self.script)
        self.assertIn('health.value.compatibility_view', self.script)
        for old_id in ('register-project', 'review-confirm', 'actor', 'send',
                       'initiative-signal', 'btn-resume', 'plugin-cards'):
            self.assertNotIn(old_id, self.page.ids)
        self.assertIn('事项与决策', self.html)
        self.assertIn('具名验收', self.html)

    def test_only_read_controls_and_requests_are_available(self):
        controls = {identifier for identifier, (tag, _) in self.page.ids.items()
                    if tag == 'button'}
        self.assertEqual({'compat-refresh', 'compat-profile-load',
                          'compat-session-load', 'compat-history-load'}, controls)
        self.assertNotIn('form', self.page.tags)
        self.assertNotIn('input', self.page.tags)
        self.assertEqual({'GET'}, set(re.findall(r"method\s*:\s*['\"]([A-Z]+)['\"]", self.script)))
        for authority in ('localStorage', 'X-Workbench-Actor', 'Idempotency-Key',
                          'submission_key', 'auto_approve'):
            self.assertNotIn(authority, self.script)

    def test_old_history_is_retained_with_explicit_read_only_boundary(self):
        self.assertIn('compat-history-load', self.page.ids)
        self.assertIn('compat-history-evidence', self.page.ids)
        self.assertIn('/api/v1/legacy', self.script)
        self.assertIn('value.read_only!==true', self.script)
        self.assertIn('value.automatic_replay!==false', self.script)
        self.assertIn('platform.db / tasks.db', self.html)
        self.assertIn('不自动迁移或重放', self.html)

    def test_profile_and_session_evidence_keep_identity_guards(self):
        for kind in ('profile', 'session'):
            self.assertEqual('select', self.page.ids['compat-' + kind][0])
            self.assertEqual('pre', self.page.ids['compat-' + kind + '-evidence'][0])
        self.assertIn('/api/v1/dump-config?profile_id=', self.script)
        self.assertIn('/api/v1/sessions/', self.script)
        self.assertIn('encodeURIComponent(id)', self.script)
        self.assertIn('value.profile?.id!==id', self.script)
        self.assertIn('value.id!==id', self.script)
        self.assertIn('read!==compatState.sessionRead', self.script)
        self.assertIn('read!==compatState.profileRead', self.script)

    def test_customer_database_and_service_identity_are_not_inferred(self):
        self.assertIn('FlowERP 客户数据库分开管理', self.html)
        self.assertNotIn('/api/v1/flowerp/', self.script)
        self.assertNotIn('iframe', self.page.tags)
        self.assertNotIn('127.0.0.1:8000', self.html)
        self.assertNotIn('127.0.0.1:8001', self.script)
        self.assertIn("url.protocol!=='http:'", self.script)
        self.assertIn("url.pathname!=='/'", self.script)
        self.assertIn('url.username || url.password', self.script)
        self.assertIn('url.search || url.hash', self.script)

    def test_query_artifacts_are_accessible_and_only_reference_current_assets(self):
        self.assertFalse(self.page.duplicates)
        self.assertEqual(['./styles.css', './app.js'], self.page.assets)
        for asset in self.page.assets:
            self.assertTrue((ROOT / 'harness_web' / asset).is_file())
        self.assertEqual('status', self.page.ids['compat-status'][1]['role'])
        self.assertIn(':focus-visible', self.styles)
        self.assertIn('overflow-wrap: anywhere', self.styles)
        self.assertIn('[hidden]', self.styles)
        self.assertIn('AbortController', self.script)
        self.assertIn('Promise.race', self.script)

    def test_server_keeps_security_utf8_and_disconnected_client_handling(self):
        server = (ROOT / 'workbench/platform_server.py').read_text(encoding='utf-8')
        for header in ('X-Content-Type-Options', 'X-Frame-Options',
                       'Content-Security-Policy', 'Cache-Control'):
            self.assertIn(header, server)
        self.assertIn('BrokenPipeError', server)
        self.assertIn('content_type += "; charset=utf-8"', server)
        self.assertIn('"no-cache"', server)

    def test_teaching_harness_does_not_claim_official_product_equivalence(self):
        self.assertIn('不代表官方 app-server 接入或产品等价', self.html)
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        gap = (ROOT / 'docs/reference/个人AI研发工作台.md').read_text(encoding='utf-8')
        self.assertIn('docs/reference/个人AI研发工作台.md', readme)
        self.assertIn('不得', gap)
        self.assertIn('app-server', gap)


if __name__ == '__main__':
    unittest.main()
