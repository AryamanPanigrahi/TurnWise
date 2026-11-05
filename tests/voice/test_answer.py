from voice.answer import render_answer, render_alert
from voice.templates import available_languages, load


def test_which_branch_with_and_without_landmark():
    r = render_answer("en", "which_branch.flyover",
                      {"on_route": "flyover", "distance_m": 340, "landmark": "Indian Oil petrol bunk"})
    assert r.text == "Take the flyover near Indian Oil petrol bunk, 350 metres ahead."
    assert not r.fell_back
    r = render_answer("en", "which_branch.service_road", {"on_route": "service_road", "distance_m": 340})
    assert r.text == "Take the service road, 350 metres ahead."


def test_kannada_and_hindi_render():
    facts = {"on_route": "flyover", "distance_m": 300}
    assert render_answer("kn", "which_branch.flyover", facts).text == "300 ಮೀಟರ್ ಮುಂದೆ ಫ್ಲೈಓವರ್ ತಗೊಳ್ಳಿ."
    assert render_answer("hi", "which_branch.flyover", facts).text == "300 मीटर आगे फ्लाईओवर लीजिए।"


def test_left_right_straight():
    assert render_answer("en", "left_or_right.left", {"distance_m": 120}).text == "Turn left in 100 metres."
    assert render_answer("en", "left_or_right.straight", {"distance_m": 1500}).text == "Go straight for 1.5 kilometres."


def test_distance_eta_and_am_i_wrong():
    assert render_answer("en", "distance_to_next", {"distance_m": 800, "maneuver": "u_turn"}).text \
        == "Next U-turn is in 800 metres."
    assert render_answer("en", "eta", {"eta_s": 610, "remaining_m": 4200}).text \
        == "4.2 kilometres left, about 11 minutes."
    assert render_answer("en", "am_i_wrong.on_route", {}).text == "You are on the right road."
    assert render_answer("en", "am_i_wrong.off_route", {"recovery_action": "u_turn", "distance_m": 300}).text \
        == "You are off route. In 300 metres, take a U-turn."


def test_never_guesses_when_facts_missing():
    not_sure = load("en").answers["not_sure"]
    bad = [
        ("which_branch.flyover", {}),                                       # no distance
        ("left_or_right.left", {"distance_m": "300"}),                       # wrong type
        ("left_or_right.left", {"distance_m": -5}),                          # invalid
        ("distance_to_next", {"distance_m": 100, "maneuver": "teleport"}),   # unknown value
        ("am_i_wrong.off_route", {"distance_m": 300}),                       # no recovery
        ("which_branch.flyover", {"on_route": "service_road", "distance_m": 300}),  # contradiction
        ("which_branch.flyover", {"on_route": "flyover", "distance_m": 300, "confidence": 0.3}),
        ("something_new", {"distance_m": 300}),                              # unknown key
    ]
    for key, facts in bad:
        r = render_answer("en", key, facts)
        assert r.text == not_sure and r.fell_back and r.reason, (key, facts, r)


def test_explicit_not_sure_is_not_a_fallback():
    r = render_answer("hi", "not_sure")
    assert r.text == "पक्का नहीं पता, स्क्रीन देखिए।" and not r.fell_back


def test_off_route_alert_always_speaks():
    r = render_alert("kn", "off_route", {"recovery": {"action": "u_turn", "distance_m": 300}})
    assert r.text == "ತಪ್ಪು ದಾರಿ! 300 ಮೀಟರ್ ನಂತರ ಯೂ-ಟರ್ನ್ ತಗೊಳ್ಳಿ."
    r = render_alert("hi", "off_route", {})
    assert r.text == "गलत रास्ता! स्क्रीन देखिए।" and r.fell_back


def test_every_language_renders_every_answer():
    """Smoke test: each language renders each answer key with complete facts."""
    facts = {"on_route": "flyover", "distance_m": 300, "maneuver": "turn_left",
             "recovery_action": "u_turn", "eta_s": 600, "remaining_m": 5000, "landmark": "X"}
    keys = ["which_branch.flyover", "left_or_right.left", "left_or_right.right",
            "left_or_right.straight", "distance_to_next", "am_i_wrong.on_route",
            "am_i_wrong.off_route", "eta"]
    for lang in available_languages():
        for key in keys:
            r = render_answer(lang, key, facts)
            assert not r.fell_back, (lang, key, r.reason)
            assert "{" not in r.text
        assert not render_alert(lang, "off_route", {"recovery": {"action": "turn_left", "distance_m": 50}}).fell_back
        assert not render_alert(lang, "back_on_route").fell_back
