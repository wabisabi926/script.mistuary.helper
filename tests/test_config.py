# -*- coding: utf-8 -*-
"""Emby 服务器发现测试。

用临时目录伪造 `addon_data/plugin.service.emby-next-gen/servers_*.json`，
字段与实测的 Emby Next Gen 4.10.x 一致。
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import config  # noqa: E402

FULL_SERVER = {
    "ServerId": "abc123",
    "ServerName": "OECT-fnOS",
    "ServerVersion": "4.10.2.0",
    "ServerUrl": "http://192.168.1.10:8096/",
    "ManualAddress": "http://192.168.1.10:8096/",
    "LocalAddress": "http://192.168.1.10:8096",
    "RemoteAddress": "http://example.ddns.net:8096",
    "AccessToken": "t" * 32,
    "UserId": "u" * 32,
    "ServerRemoved": False,
}


class ServerDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.profile = tempfile.mkdtemp(prefix="mistuary-profile-")
        self.addon_dir = os.path.join(self.profile, "addon_data", config.EMBY_ADDON_ID)
        os.makedirs(self.addon_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.profile, ignore_errors=True)

    def _write(self, name, data):
        path = os.path.join(self.addon_dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        return path

    def test_no_files_returns_empty(self):
        self.assertEqual(config.load_servers(self.profile), [])

    def test_reads_full_server(self):
        self._write("servers_abc.json", FULL_SERVER)
        servers = config.load_servers(self.profile)
        self.assertEqual(len(servers), 1)
        server = servers[0]
        self.assertEqual(server.server_id, "abc123")
        self.assertEqual(server.name, "OECT-fnOS")
        self.assertEqual(server.token, "t" * 32)
        self.assertTrue(server.usable)

    def test_base_url_has_no_trailing_slash(self):
        self._write("servers_abc.json", FULL_SERVER)
        self.assertEqual(config.load_servers(self.profile)[0].base_url, "http://192.168.1.10:8096")

    def test_removed_server_is_skipped(self):
        removed = dict(FULL_SERVER, ServerRemoved=True)
        self._write("servers_gone.json", removed)
        self.assertEqual(config.load_servers(self.profile), [])

    def test_missing_token_is_not_usable(self):
        broken = dict(FULL_SERVER, AccessToken="")
        self._write("servers_x.json", broken)
        self.assertEqual(config.load_servers(self.profile), [])

    def test_address_priority(self):
        """ServerUrl > ManualAddress > LocalAddress > RemoteAddress。"""
        only_remote = dict(FULL_SERVER, ServerUrl="", ManualAddress="", LocalAddress="")
        self._write("servers_r.json", only_remote)
        self.assertEqual(config.load_servers(self.profile)[0].base_url,
                         "http://example.ddns.net:8096")

    def test_manual_address_beats_local(self):
        """实测 ManualAddress 和 ServerUrl 都要算进去，否则用户手填的地址会被忽略。"""
        data = dict(FULL_SERVER, ServerUrl="", ManualAddress="http://manual:8096",
                    LocalAddress="http://local:8096")
        self._write("servers_m.json", data)
        self.assertEqual(config.load_servers(self.profile)[0].base_url, "http://manual:8096")

    def test_corrupted_json_is_skipped(self):
        path = os.path.join(self.addon_dir, "servers_bad.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{oops")
        self.assertEqual(config.load_servers(self.profile), [])

    def test_find_server_by_id(self):
        self._write("servers_a.json", dict(FULL_SERVER, ServerId="aaa"))
        self._write("servers_b.json", dict(FULL_SERVER, ServerId="bbb"))
        found = config.find_server("bbb", profile=self.profile)
        self.assertEqual(found.server_id, "bbb")

    def test_find_server_defaults_to_first(self):
        self._write("servers_a.json", dict(FULL_SERVER, ServerId="aaa"))
        self._write("servers_b.json", dict(FULL_SERVER, ServerId="bbb"))
        self.assertEqual(config.find_server("", profile=self.profile).server_id, "aaa")

    def test_unknown_id_falls_back_to_first(self):
        """设置里钉的服务器被删了：退回第一个，别让功能整个失效。"""
        self._write("servers_a.json", dict(FULL_SERVER, ServerId="aaa"))
        self.assertEqual(config.find_server("gone", profile=self.profile).server_id, "aaa")

    def test_no_server_returns_none(self):
        self.assertIsNone(config.find_server("", profile=self.profile))

    def test_repr_does_not_leak_token(self):
        self._write("servers_abc.json", FULL_SERVER)
        text = repr(config.load_servers(self.profile)[0])
        self.assertNotIn("t" * 32, text)


if __name__ == "__main__":
    unittest.main()
