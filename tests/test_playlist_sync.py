# -*- coding: utf-8 -*-
import unittest

from lib import playlist_sync


class FollowingEpisodesTest(unittest.TestCase):
    def test_picks_after_current_in_order(self):
        episodes = [
            {"episodeid": 3, "episode": 3},
            {"episodeid": 1, "episode": 1},
            {"episodeid": 2, "episode": 2},
        ]
        picked = playlist_sync.following_episodes(episodes, 1)
        self.assertEqual([e["episodeid"] for e in picked], [2, 3])

    def test_unknown_current_returns_empty(self):
        self.assertEqual(playlist_sync.following_episodes(
            [{"episodeid": 2, "episode": 2}], 0), [])

    def test_bad_episode_numbers_are_skipped(self):
        episodes = [{"episodeid": 1, "episode": "x"}, {"episodeid": 2}, {"episodeid": 3, "episode": 2}]
        picked = playlist_sync.following_episodes(episodes, 1)
        self.assertEqual([e["episodeid"] for e in picked], [3])


class FollowingFilesTest(unittest.TestCase):
    def test_picks_after_current_and_filters_sidecars(self):
        files = ["/m/a.mkv", "/m/a.srt", "/m/b.mp4", "/m/c.nfo"]
        self.assertEqual(playlist_sync.following_files(files, "/m/a.mkv"), ["/m/b.mp4"])

    def test_current_not_found_returns_empty(self):
        self.assertEqual(playlist_sync.following_files(["/m/a.mkv", "/m/b.mp4"], "/m/z.mkv"), [])

    def test_paths_are_normalized(self):
        files = ["D:\\m\\a.mkv", "D:\\m\\b.mp4"]
        self.assertEqual(playlist_sync.following_files(files, "d:/m/a.mkv"), ["D:\\m\\b.mp4"])

    def test_plugin_paths_without_extension_are_playable(self):
        files = ["plugin://video/?id=1", "plugin://video/?id=2"]
        self.assertEqual(playlist_sync.following_files(files, "plugin://video/?id=1"), ["plugin://video/?id=2"])

    def test_audio_files_are_not_added_to_video_folders(self):
        files = ["/m/a.mkv", "/m/b.mp3", "/m/c.flac"]
        self.assertEqual(playlist_sync.following_files(files, "/m/a.mkv"), [])

    def test_audio_folder_picks_only_audio(self):
        files = ["/m/a.mp3", "/m/cover.jpg", "/m/b.flac", "/m/list.m3u", "/m/c.mkv"]
        self.assertEqual(
            playlist_sync.following_files(files, "/m/a.mp3", "audio"),
            ["/m/b.flac"],
        )


class ShouldExtendTest(unittest.TestCase):
    def test_only_single_item_and_any_switch(self):
        self.assertFalse(playlist_sync.should_extend(False, False, 1))
        self.assertTrue(playlist_sync.should_extend(True, False, 1))
        self.assertTrue(playlist_sync.should_extend(False, True, 1))
        self.assertTrue(playlist_sync.should_extend(True, True, 1))
        self.assertFalse(playlist_sync.should_extend(True, True, 2))
        self.assertFalse(playlist_sync.should_extend(True, True, "x"))


class ChooseModeTest(unittest.TestCase):
    def test_episode_prefers_season(self):
        self.assertEqual(
            playlist_sync.choose_mode("video", {"type": "episode"}, True, True),
            "season",
        )

    def test_episode_without_season_switch_falls_back_to_folder(self):
        self.assertEqual(
            playlist_sync.choose_mode("video", {"type": "episode"}, False, True),
            "folder",
        )

    def test_movie_or_audio_uses_folder(self):
        self.assertEqual(playlist_sync.choose_mode("video", {"type": "movie"}, True, True), "folder")
        self.assertEqual(playlist_sync.choose_mode("audio", {"type": "song"}, True, True), "folder")

    def test_nothing_enabled(self):
        self.assertIsNone(playlist_sync.choose_mode("video", {"type": "episode"}, False, False))


class FolderPathTest(unittest.TestCase):
    def test_uses_folderpath_first(self):
        item = {"folderpath": "/m/", "file": "/m/a.mkv"}
        self.assertEqual(playlist_sync.folder_path_for(item), "/m")

    def test_falls_back_to_local_file_directory(self):
        self.assertEqual(playlist_sync.folder_path_for({"file": "D:\\m\\a.mkv"}), "D:/m")

    def test_falls_back_to_dav_directory(self):
        self.assertEqual(
            playlist_sync.folder_path_for({"file": "dav://nas/music/01.m4a"}),
            "dav://nas/music",
        )

    def test_plugin_path_without_folder_is_ignored(self):
        self.assertEqual(playlist_sync.folder_path_for({"file": "plugin://video/?id=1"}), "")

    def test_http_stream_is_not_listed_as_folder(self):
        self.assertEqual(playlist_sync.folder_path_for({"file": "http://x/video.mkv"}), "")


class ItemMediaKindTest(unittest.TestCase):
    def test_item_type_wins(self):
        self.assertEqual(playlist_sync.item_media_kind({"type": "song", "file": "/m/a.mkv"}), "audio")
        self.assertEqual(playlist_sync.item_media_kind({"type": "episode", "file": "/m/a.mp3"}), "video")

    def test_unknown_type_falls_back_to_extension(self):
        self.assertEqual(playlist_sync.item_media_kind({"type": "unknown", "file": "/m/a.m4a"}), "audio")
        self.assertEqual(playlist_sync.item_media_kind({"type": "unknown", "file": "/m/a.mkv"}), "video")

    def test_plugin_path_falls_back_to_player_type(self):
        self.assertEqual(playlist_sync.item_media_kind({"file": "plugin://x/?id=1"}, "audio"), "audio")
        self.assertEqual(playlist_sync.item_media_kind({"file": "plugin://x/?id=1"}, "video"), "video")


class IsEpisodeTest(unittest.TestCase):
    def test_type_or_season_episode(self):
        self.assertTrue(playlist_sync.is_episode({"type": "episode"}))
        self.assertTrue(playlist_sync.is_episode({"season": 1, "episode": 2}))
        self.assertFalse(playlist_sync.is_episode({"season": 1, "episode": 0}))
        self.assertFalse(playlist_sync.is_episode({"type": "movie"}))

    def test_movie_minus_one_values_are_not_episodes(self):
        self.assertFalse(playlist_sync.is_episode({"type": "unknown", "season": -1, "episode": -1}))
        self.assertFalse(playlist_sync.is_episode({"season": -1, "episode": 3}))


class _Log:
    def debug(self, *args):
        pass

    def error(self, *args):
        pass


class ExtendPlaylistTest(unittest.TestCase):
    def _patch(self, **kwargs):
        self._old = {name: getattr(playlist_sync, name) for name in kwargs}
        for name, value in kwargs.items():
            setattr(playlist_sync, name, value)

    def tearDown(self):
        for name, value in getattr(self, "_old", {}).items():
            setattr(playlist_sync, name, value)

    def test_current_item_requests_only_allowed_fields(self):
        seen = {}

        def fake_rpc(method, params):
            seen["method"] = method
            seen.update(params)
            return {"item": {"id": 7, "type": "song", "file": "/m/a.m4a"}}

        self._patch(_rpc=fake_rpc)
        item = playlist_sync.current_item(0)
        self.assertEqual(seen["method"], "Player.GetItem")
        self.assertEqual(seen["playerid"], 0)
        self.assertEqual(set(seen["properties"]), {"title", "season", "episode", "file"})
        self.assertEqual(item["file"], "/m/a.m4a")

    def test_audio_folder_completion_adds_following_tracks(self):
        calls = []

        self._patch(
            player_context=lambda: (0, 0, "audio"),
            playlist_length=lambda playlistid: 1,
            current_item=lambda playerid: {"type": "song", "file": "dav://nas/music/01.m4a"},
            folder_files=lambda folder: [
                "dav://nas/music/01.m4a",
                "dav://nas/music/02.m4a",
                "dav://nas/music/cover.jpg",
            ],
            _rpc=lambda method, params: (calls.append((method, params)) or "OK"),
            log=_Log(),
        )
        added = playlist_sync.extend_playlist(False, True)
        self.assertEqual(added, 1)
        self.assertEqual(calls, [(
            "Playlist.Add",
            {"playlistid": 0, "item": {"file": "dav://nas/music/02.m4a"}},
        )])

    def test_episode_prefers_season_over_folder(self):
        calls = []

        def fail_folder(folder):
            raise AssertionError("folder completion must not run for a season episode")

        self._patch(
            player_context=lambda: (1, 1, "video"),
            playlist_length=lambda playlistid: 1,
            current_item=lambda playerid: {
                "id": 5, "type": "episode", "season": 1, "episode": 2, "file": "/tv/s01e02.mkv",
            },
            season_targets=lambda item: [{"episodeid": 6}],
            folder_files=fail_folder,
            _rpc=lambda method, params: (calls.append((method, params)) or "OK"),
            log=_Log(),
        )
        added = playlist_sync.extend_playlist(True, True)
        self.assertEqual(added, 1)
        self.assertEqual(calls, [(
            "Playlist.Add",
            {"playlistid": 1, "item": {"episodeid": 6}},
        )])

    def test_episode_without_season_data_falls_back_to_folder(self):
        calls = []

        self._patch(
            player_context=lambda: (1, 1, "video"),
            playlist_length=lambda playlistid: 1,
            current_item=lambda playerid: {
                "type": "episode", "season": None, "episode": None, "file": "/tv/s01e02.mkv",
            },
            season_targets=lambda item: None,
            folder_files=lambda folder: ["/tv/s01e02.mkv", "/tv/s01e03.mkv"],
            _rpc=lambda method, params: (calls.append((method, params)) or "OK"),
            log=_Log(),
        )
        added = playlist_sync.extend_playlist(True, True)
        self.assertEqual(added, 1)
        self.assertEqual(calls, [(
            "Playlist.Add",
            {"playlistid": 1, "item": {"file": "/tv/s01e03.mkv"}},
        )])

    def test_movie_with_minus_one_season_uses_folder(self):
        calls = []

        self._patch(
            player_context=lambda: (1, 1, "video"),
            playlist_length=lambda playlistid: 1,
            current_item=lambda playerid: {
                "type": "movie", "season": -1, "episode": -1, "file": "/movies/a.mkv",
            },
            folder_files=lambda folder: ["/movies/a.mkv", "/movies/b.mkv"],
            _rpc=lambda method, params: (calls.append((method, params)) or "OK"),
            log=_Log(),
        )
        added = playlist_sync.extend_playlist(True, True)
        self.assertEqual(added, 1)
        self.assertEqual(calls, [(
            "Playlist.Add",
            {"playlistid": 1, "item": {"file": "/movies/b.mkv"}},
        )])


class LooksLikeVideoTest(unittest.TestCase):
    def test_extensions(self):
        self.assertTrue(playlist_sync.looks_like_video("/m/a.mkv"))
        self.assertTrue(playlist_sync.looks_like_video("/m/a.MP4"))
        self.assertFalse(playlist_sync.looks_like_video("/m/a.srt"))
        self.assertFalse(playlist_sync.looks_like_video("/m/a.nfo"))
        self.assertFalse(playlist_sync.looks_like_video("/m/a.mp3"))
        self.assertFalse(playlist_sync.looks_like_video(""))
        self.assertTrue(playlist_sync.looks_like_video("plugin://video/?id=1"))
        self.assertTrue(playlist_sync.looks_like_video("/m/a.mkv?dl=1"))


class LooksLikeAudioTest(unittest.TestCase):
    def test_extensions(self):
        self.assertTrue(playlist_sync.looks_like_audio("/m/a.mp3"))
        self.assertTrue(playlist_sync.looks_like_audio("/m/a.FLAC"))
        self.assertTrue(playlist_sync.looks_like_audio("/m/a.m4a?token=1"))
        self.assertFalse(playlist_sync.looks_like_audio("/m/a.mkv"))
        self.assertFalse(playlist_sync.looks_like_audio("/m/a.jpg"))
        self.assertFalse(playlist_sync.looks_like_audio(""))
        self.assertTrue(playlist_sync.looks_like_audio("plugin://music/?id=1"))


if __name__ == "__main__":
    unittest.main()
