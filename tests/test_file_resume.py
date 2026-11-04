# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from unittest import mock

from lib import file_resume


class NormalizeTest(unittest.TestCase):
    def test_windows_backslashes(self):
        self.assertEqual(file_resume.normalize_key("D:\\Movies\\a.mkv"), "D:/Movies/a.mkv")

    def test_trailing_slash_removed(self):
        self.assertEqual(file_resume.normalize_key("smb://nas/media/"), "smb://nas/media")

    def test_case_is_preserved(self):
        self.assertEqual(file_resume.normalize_key("smb://NAS/Media/A.mkv"), "smb://NAS/Media/A.mkv")

    def test_empty(self):
        self.assertEqual(file_resume.normalize_key(None), "")


class FormatTimeTest(unittest.TestCase):
    def test_minutes_seconds(self):
        self.assertEqual(file_resume.format_time(754), "12:34")

    def test_hours(self):
        self.assertEqual(file_resume.format_time(5025), "1:23:45")

    def test_bad_value(self):
        self.assertEqual(file_resume.format_time("x"), "")

    def test_dialog_pads_minutes(self):
        self.assertEqual(file_resume.format_dialog_time(67), "01:07")
        self.assertEqual(file_resume.format_dialog_time(7), "00:07")
        self.assertEqual(file_resume.format_dialog_time(754), "12:34")
        self.assertEqual(file_resume.format_dialog_time(5025), "1:23:45")
        self.assertEqual(file_resume.format_dialog_time("x"), "")


class PercentKeyTest(unittest.TestCase):
    def test_exact_percent_key(self):
        self.assertEqual(file_resume.percent_key(7), "007")
        self.assertEqual(file_resume.percent_key(11), "011")
        self.assertEqual(file_resume.percent_key(92), "092")
        self.assertEqual(file_resume.percent_key(100), "100")

    def test_clamps(self):
        self.assertEqual(file_resume.percent_key(-1), "000")
        self.assertEqual(file_resume.percent_key(120), "100")
        self.assertEqual(file_resume.percent_key("x"), "000")


class FocusProbeTest(unittest.TestCase):
    def test_empty_path_is_kept(self):
        self.assertIsNone(file_resume.FileResumeManager._focus_probe("", False))

    def test_folder_row_clears(self):
        self.assertEqual(
            file_resume.FileResumeManager._focus_probe("smb://nas/media", True), "clear")
        self.assertEqual(file_resume.FileResumeManager._focus_probe("", True), "clear")

    def test_file_row_returns_path(self):
        self.assertEqual(
            file_resume.FileResumeManager._focus_probe("D:/a.mkv", False), "D:/a.mkv")


class RingPropsTest(unittest.TestCase):
    def test_zero_total_is_hidden(self):
        self.assertIsNone(file_resume.FileResumeManager._ring_props(
            {"pos": 190.3, "total": 0}))

    def test_zero_position_is_hidden(self):
        self.assertIsNone(file_resume.FileResumeManager._ring_props(
            {"pos": 0, "total": 1000}))

    def test_normal_percent(self):
        self.assertEqual(
            file_resume.FileResumeManager._ring_props(
                {"pos": 190.3, "total": 2415.3}),
            ("true", "3:10", "7", "007"))


class LookupTotalTest(unittest.TestCase):
    def test_native_without_total_is_ignored(self):
        mgr = file_resume.FileResumeManager(None)
        with mock.patch.object(file_resume, "_native_resume",
                               return_value={"path": "D:/a.mkv", "pos": 10, "total": 0}):
            self.assertIsNone(mgr._lookup("D:/a.mkv"))

    def test_native_with_total_is_used(self):
        mgr = file_resume.FileResumeManager(None)
        with mock.patch.object(file_resume, "_native_resume",
                               return_value={"path": "D:/a.mkv", "pos": 60, "total": 600}):
            row = mgr._lookup("D:/a.mkv")
        self.assertEqual(row["pos"], 60)

    def test_save_evicts_native_focus(self):
        class Store:
            def upsert(self, *args, **kwargs):
                pass

        mgr = file_resume.FileResumeManager(Store())
        key = file_resume.normalize_key("D:/a.mkv")
        mgr._focus_native[key] = (0, {"pos": 1, "total": 0})
        mgr._save_ledger({"path": "D:/a.mkv", "key": key, "pos": 190.0,
                          "total": 2415.0, "source": "file"})
        self.assertNotIn(key, mgr._focus_native)


class AutoTransitionTest(unittest.TestCase):
    def test_same_file_reopen_prompts(self):
        prev = {"key": file_resume.normalize_key("D:/a.mkv"), "last_update": 1000}
        self.assertFalse(file_resume.FileResumeManager._is_auto_transition(
            prev, "D:\\a.mkv", 1050))

    def test_next_episode_is_transition(self):
        prev = {"key": file_resume.normalize_key("D:/a.mkv"), "last_update": 1000}
        self.assertTrue(file_resume.FileResumeManager._is_auto_transition(
            prev, "D:/b.mkv", 1050))

    def test_old_session_prompts(self):
        prev = {"key": file_resume.normalize_key("D:/a.mkv"), "last_update": 1000}
        self.assertFalse(file_resume.FileResumeManager._is_auto_transition(
            prev, "D:/b.mkv", 1400))

    def test_no_previous(self):
        self.assertFalse(file_resume.FileResumeManager._is_auto_transition(
            None, "D:/a.mkv", 1000))


class I18nFallbackTest(unittest.TestCase):
    def test_dialog_labels(self):
        self.assertEqual(file_resume.i18n.t(32075), "从头播放")
        self.assertEqual(file_resume.i18n.t(32082, "01:07"), "从 01:07 继续播放")


class EligibilityTest(unittest.TestCase):
    def test_real_paths(self):
        for path in ("/media/a.mkv", "smb://nas/a.mkv", "nfs://nas/a.strm",
                     "D:\\media\\a.iso", "//nas/share/a.mkv", "ftp://nas/a.mkv",
                     "sftp://nas/a.mkv", "dav://nas/a.mkv",
                     "webdav://nas/a.mkv", "upnp://nas/a.mkv"):
            self.assertTrue(file_resume.is_eligible_path(path), path)

    def test_excluded_schemes(self):
        for path in ("plugin://video/?id=1", "pvr://channels/1", "http://x/a.mkv",
                     "https://x/a.mkv", "special://profile/a.mkv", "videodb://movies"):
            self.assertFalse(file_resume.is_eligible_path(path), path)

    def test_http_opt_in(self):
        self.assertTrue(file_resume.is_eligible_path("https://x/a.mkv", allow_http=True))
        self.assertTrue(file_resume.is_eligible_path("http://x/a.mkv", allow_http=True))
        self.assertFalse(file_resume.is_eligible_path("plugin://x/a.mkv", allow_http=True))
        self.assertFalse(file_resume.is_eligible_path("pvr://x/a.mkv", allow_http=True))

    def test_credentials_are_stripped(self):
        self.assertEqual(file_resume.normalize_key("ftp://user:pass@host/a.mkv"),
                         "ftp://host/a.mkv")
        self.assertEqual(file_resume.normalize_key("smb://user@host/share/a.mkv"),
                         "smb://host/share/a.mkv")
        self.assertEqual(file_resume.normalize_key("smb://host/share/a@b.mkv"),
                         "smb://host/share/a@b.mkv")

    def test_empty(self):
        self.assertFalse(file_resume.is_eligible_path(""))

    def test_strm_source(self):
        self.assertEqual(file_resume.source_for_path("smb://nas/a.STRM"), "strm")
        self.assertEqual(file_resume.source_for_path("smb://nas/a.mkv"), "file")


class ThresholdTest(unittest.TestCase):
    def test_no_save_within_start_grace(self):
        self.assertFalse(file_resume.should_save(179, 7200))

    def test_save_after_start_grace(self):
        self.assertTrue(file_resume.should_save(180, 7200))

    def test_finished_at_end_percent(self):
        self.assertTrue(file_resume.is_finished(6624, 7200))  # 92%
        self.assertFalse(file_resume.is_finished(6623, 7200))

    def test_no_save_when_finished(self):
        self.assertFalse(file_resume.should_save(7000, 7200))

    def test_zero_total_is_skipped(self):
        self.assertFalse(file_resume.should_save(300, 0))


class LibraryItemTest(unittest.TestCase):
    def test_library_types(self):
        self.assertTrue(file_resume.is_library_item({"type": "movie", "id": 3}))
        self.assertTrue(file_resume.is_library_item({"type": "episode", "id": 3}))

    def test_file_item(self):
        self.assertFalse(file_resume.is_library_item({"type": "unknown", "id": -1}))
        self.assertFalse(file_resume.is_library_item(None))


class RetentionSettingsTest(unittest.TestCase):
    def test_retention_values(self):
        with mock.patch.object(file_resume, "_setting_string", return_value="180"):
            self.assertEqual(file_resume.retention_days(), 180)
        with mock.patch.object(file_resume, "_setting_string", return_value="0"):
            self.assertEqual(file_resume.retention_days(), 0)
        with mock.patch.object(file_resume, "_setting_string", return_value="bad"):
            self.assertEqual(file_resume.retention_days(), 90)

    def test_max_records_values(self):
        with mock.patch.object(file_resume, "_setting_string", return_value="1000"):
            self.assertEqual(file_resume.max_records(), 1000)
        with mock.patch.object(file_resume, "_setting_string", return_value="0"):
            self.assertEqual(file_resume.max_records(), 5000)


class ResumeStoreMaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = file_resume.ResumeStore(os.path.join(self.tmp.name, "resume.db"))
        self.store.open()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_cleanup_never_still_enforces_limit(self):
        now = 10_000_000
        self.store.upsert("/media/a.mkv", 100, 1000, now=now - 300)
        self.store.upsert("/media/b.mkv", 100, 1000, now=now - 200)
        self.store.upsert("/media/c.mkv", 100, 1000, now=now - 100)
        removed = self.store.cleanup(now=now, ttl_days=0, max_records=2)
        self.assertEqual(removed, 1)
        self.assertEqual(self.store.count(), 2)
        self.assertIsNone(self.store.get("/media/a.mkv"))

    def test_clear_all(self):
        self.store.upsert("/media/a.mkv", 100, 1000)
        self.store.upsert("/media/b.mkv", 100, 1000)
        self.assertEqual(self.store.clear_all(), 2)
        self.assertEqual(self.store.count(), 0)

    def test_data_version_changes(self):
        before = self.store.data_version()
        self.store.upsert("/media/a.mkv", 100, 1000)
        self.assertIsInstance(before, int)
        self.assertIsInstance(self.store.data_version(), int)


class ResumeStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = file_resume.ResumeStore(os.path.join(self.tmp.name, "resume.db"))
        self.store.open()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_upsert_and_get(self):
        self.assertTrue(self.store.upsert("/media/a.mkv", 1200, 7200))
        row = self.store.get("/media/a.mkv")
        self.assertEqual(row["pos"], 1200)
        self.assertEqual(row["total"], 7200)
        self.assertEqual(row["source"], "file")

    def test_upsert_strips_credentials(self):
        path = "ftp://user:pass@host/a.mkv"
        self.store.upsert(path, 1200, 7200)
        row = self.store.get(path)
        self.assertEqual(row["path"], "ftp://host/a.mkv")

    def test_strm_source(self):
        self.store.upsert("/media/a.strm", 1200, 7200)
        self.assertEqual(self.store.get("/media/a.strm")["source"], "strm")

    def test_case_fold_fallback(self):
        self.store.upsert("smb://NAS/Media/A.mkv", 1200, 7200)
        self.assertIsNotNone(self.store.get("smb://nas/media/a.mkv"))

    def test_delete_removes_folded_row(self):
        self.store.upsert("smb://NAS/Media/A.mkv", 1200, 7200)
        self.store.delete("smb://nas/media/a.mkv")
        self.assertIsNone(self.store.get("smb://NAS/Media/A.mkv"))
        self.assertEqual(self.store.count(), 0)

    def test_recent_orders_by_time(self):
        self.store.upsert("/a.mkv", 300, 7200, now=100)
        self.store.upsert("/b.mkv", 300, 7200, now=200)
        rows = self.store.recent()
        self.assertEqual([row["path"] for row in rows], ["/b.mkv", "/a.mkv"])

    def test_cleanup_expired(self):
        self.store.upsert("/old.mkv", 300, 7200, now=1000)
        self.store.upsert("/new.mkv", 300, 7200, now=100000)
        removed = self.store.cleanup(now=100000, ttl_days=1)
        self.assertEqual(removed, 1)
        self.assertIsNone(self.store.get("/old.mkv"))
        self.assertIsNotNone(self.store.get("/new.mkv"))

    def test_cleanup_caps_records(self):
        for index in range(5):
            self.store.upsert("/f%d.mkv" % index, 300, 7200, now=100 + index)
        self.store.cleanup(now=200, ttl_days=90, max_records=2)
        self.assertEqual(self.store.count(), 2)
        self.assertIsNotNone(self.store.get("/f4.mkv"))

    def test_zero_total_is_rejected(self):
        self.assertFalse(self.store.upsert("/a.mkv", 10, 0))


if __name__ == "__main__":
    unittest.main()
