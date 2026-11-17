"""Machine-specific settings for the icon tools, read from a JSON config file (nothing is
hard-coded to one machine). Copy config.example.json to config.json and edit it, or point
--config / the TF2C_ICONS_CONFIG environment variable at another file.

Keys:
  tf2c_game_dir     the TF2 Classified game folder (".../tf2classified": custom/, vpks/)
  tf2_dir           optional: a TF2 (dedicated server or client) root containing tf/ and hl2/
  tf2_client_dir    optional: a TF2 client root (the dedicated server lacks the texture VPK archives)
  search_extra      optional: extra [kind, path] sources searched after the game, kind "dir" or "vpk"
                    (e.g. a staged mod tree whose models are not installed yet)
  staging_dir       bucket icons: a loose game tree holding the models + materials to render
                    (searched first; the renderer resolves VMTs / VTFs against it)
  customslop_tools  bucket icons: the tools/ folder of a tf2c-customslop checkout
                    (https://github.com/AgitationSkeleton/tf2c-customslop), which holds the v2 renderer
  out_dir           where generated files go (default: ./out)
"""
import glob
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_path = None
_cache = None


def use(path):
    """Select a config file (the --config option); call before anything reads a key."""
    global _path, _cache
    _path, _cache = path, None


def config():
    global _cache
    if _cache is None:
        p = _path or os.environ.get("TF2C_ICONS_CONFIG") or os.path.join(REPO, "config.json")
        _cache = {}
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                _cache = json.load(f)
    return _cache


def opt(key, default=None):
    v = config().get(key)
    return default if v in (None, "") else v


def need(key):
    v = opt(key)
    if v is None:
        raise SystemExit("config key %r is not set (copy config.example.json to config.json)" % key)
    return v


def out_dir():
    d = opt("out_dir", os.path.join(REPO, "out"))
    return d if os.path.isabs(d) else os.path.join(REPO, d)


def search_order(first=()):
    """[(kind, path)] in the game's own order: custom/* (alphabetical, loose folders and VPKs),
    the TF2C VPKs, TF2 / HL2 content, the game folder, then search_extra. `first` goes in front."""
    tf2c = need("tf2c_game_dir")
    tf2 = opt("tf2_dir", "")
    tf2_client = opt("tf2_client_dir", tf2)
    order = list(first)
    for p in sorted(glob.glob(os.path.join(tf2c, "custom", "*"))):
        order.append(("vpk", p) if p.endswith(".vpk") else ("dir", p))
    for name in ("tf2c_assets_dir.vpk", "mb2_tf_content_dir.vpk", "mb2_shared_content_dir.vpk",
                 "tf2c_overrides_dir.vpk"):
        order.append(("vpk", os.path.join(tf2c, "vpks", name)))
    if tf2 or tf2_client:
        order += [("vpk", os.path.join(tf2_client, "tf", "tf2_textures_dir.vpk")),
                  ("vpk", os.path.join(tf2, "tf", "tf2_misc_dir.vpk")),
                  ("vpk", os.path.join(tf2_client, "hl2", "hl2_textures_dir.vpk")),
                  ("vpk", os.path.join(tf2, "hl2", "hl2_misc_dir.vpk"))]
    order.append(("dir", tf2c))
    order += [tuple(x) for x in opt("search_extra", []) or []]
    # a numbered VPK archive (name_000.vpk) is read through its _dir.vpk, never on its own
    return [(k, p) for k, p in order
            if not (k == "vpk" and p[-8:-4].startswith("_") and p[-7:-4].isdigit())]
