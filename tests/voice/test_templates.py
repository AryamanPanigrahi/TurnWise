import string

from voice.templates import available_languages, load


def _strings(value):
    if isinstance(value, dict):
        return list(value.values())
    return [value]


def test_pilot_languages_present():
    langs = available_languages()
    for lang in ("kn", "hi", "en"):
        assert lang in langs


def test_all_templates_load_and_validate():
    for lang in available_languages():
        ts = load(lang)
        assert ts.lang == lang


def test_languages_have_same_vocab_keys_as_english():
    """Every language must cover every branch/maneuver/recovery value English does."""
    en = load("en")
    for lang in available_languages():
        ts = load(lang)
        for section in ("branch", "direction", "maneuver", "recovery"):
            missing = set(en.vocab[section]) - set(ts.vocab[section])
            assert not missing, f"{lang}: vocab.{section} missing {missing}"


def test_placeholders_are_known():
    allowed = {"distance", "branch", "direction", "maneuver", "recovery",
               "landmark", "eta", "remaining"}
    for lang in available_languages():
        ts = load(lang)
        for section in (ts.answers, ts.alerts):
            for key, value in section.items():
                for text in _strings(value):
                    fields = {f for _, f, _, _ in string.Formatter().parse(text) if f}
                    assert fields <= allowed, f"{lang}:{key} unknown {fields - allowed}"
