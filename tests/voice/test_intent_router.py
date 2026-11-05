from voice.intent_router import route, tokenize

CASES = {
    "en": [
        ("Flyover or service road?", "which_branch"),
        ("Should I go left or right?", "left_or_right"),
        ("How far is the next turn?", "distance_to_next"),
        ("Am I going the wrong way?", "am_i_wrong"),
        ("Am I on the right road?", "am_i_wrong"),
        ("How much time left?", "eta"),
        ("When will I reach?", "eta"),
        ("Can you repeat that", "repeat"),
        ("How far is the left turn?", "distance_to_next"),
        ("What is the weather today", "unknown"),
    ],
    "kn": [
        ("ಫ್ಲೈಓವರ್ ಅಥವಾ ಸರ್ವಿಸ್ ರೋಡ್?", "which_branch"),
        ("ಎಡಕ್ಕೆ ಹೋಗಬೇಕಾ ಬಲಕ್ಕೆ?", "left_or_right"),
        ("ಮುಂದಿನ ತಿರುವು ಎಷ್ಟು ದೂರ?", "distance_to_next"),
        ("ನಾನು ತಪ್ಪು ದಾರಿಯಲ್ಲಿ ಇದ್ದೀನಾ?", "am_i_wrong"),
        ("ಎಷ್ಟು ಹೊತ್ತು ಆಗುತ್ತೆ?", "eta"),
        ("ಮತ್ತೆ ಹೇಳಿ", "repeat"),
        ("flyover ಮೇಲೆ ಹೋಗಬೇಕಾ?", "which_branch"),  # code-mixed
        ("ಊಟ ಆಯ್ತಾ", "unknown"),
    ],
    "hi": [
        ("फ्लाईओवर या सर्विस रोड?", "which_branch"),
        ("बाएं जाना है या दाएं?", "left_or_right"),
        ("अगला मोड़ कितनी दूर है?", "distance_to_next"),
        ("क्या मैं गलत रास्ते पर हूँ?", "am_i_wrong"),
        ("कितना समय लगेगा?", "eta"),
        ("फिर से बोलो", "repeat"),
        ("ऊपर वाला लूँ या नीचे वाला?", "which_branch"),
        ("आज मौसम कैसा है", "unknown"),
    ],
}


def test_intents_per_language():
    for lang, cases in CASES.items():
        for text, expected in cases:
            got = route(text, lang)
            assert got.name == expected, f"{lang}: {text!r} -> {got.name}, expected {expected}"


def test_branch_options_in_spoken_order():
    assert route("Service road or flyover?", "en").slots == {"options": ["service_road", "flyover"]}
    assert route("ಫ್ಲೈಓವರ್ ಅಥವಾ ಸರ್ವಿಸ್ ರೋಡ್?", "kn").slots == {"options": ["flyover", "service_road"]}
    assert route("ऊपर वाला लूँ या नीचे वाला?", "hi").slots == {"options": ["flyover", "service_road"]}


def test_matched_keyword_reported_for_logging():
    assert route("how far?", "en").matched == "how far"


def test_empty_and_punctuation_only():
    for text in ("", "   ", "?!।"):
        assert route(text, "hi").name == "unknown"


def test_tokenize_strips_danda_and_zwnj():
    assert tokenize("सही है।") == ["सही", "है"]
    assert tokenize("ಅಂಡರ್‌ಪಾಸ್") == tokenize("ಅಂಡರ್ಪಾಸ್")
