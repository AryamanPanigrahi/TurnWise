from voice.llm_fallback import classify, parse_label


def _chat(reply, cost=0.002, exc=None, seen=None):
    def chat(messages, timeout):
        if seen is not None:
            seen.append((messages, timeout))
        if exc:
            raise exc
        return reply, cost
    return chat


def test_parse_label_accepts_only_known_labels():
    assert parse_label("eta") == "eta"
    assert parse_label("  which_branch\n") == "which_branch"
    assert parse_label("Which_Branch.") == "which_branch"
    assert parse_label("Take the flyover in 300 m") == "unknown"
    assert parse_label("turn_left") == "unknown"
    assert parse_label("") == "unknown"


def test_classify_returns_intent_and_cost():
    seen = []
    intent, cost, err = classify("ಮೇಲೆ ಹೋಗ್ಲಾ ಫ್ಲೈಓವರ್", "kn", _chat("which_branch", seen=seen), 2.5)
    assert intent.name == "which_branch" and intent.slots == {"options": ["flyover"]}
    assert intent.matched == "llm:which_branch" and cost == 0.002 and err is None
    messages, timeout = seen[0]
    assert timeout == 2.5 and "Kannada" in messages[0]["content"]
    assert messages[1]["content"] == "<q>ಮೇಲೆ ಹೋಗ್ಲಾ ಫ್ಲೈಓವರ್</q>"


def test_model_trying_to_answer_is_rejected():
    intent, _, _ = classify("which way", "en", _chat("Go left at the temple"), 2.0)
    assert intent.name == "unknown"


def test_timeout_error_and_no_budget_fall_back():
    assert classify("x", "en", _chat("", exc=TimeoutError()), 1.0)[0].name == "unknown"
    i, cost, err = classify("x", "en", _chat("", exc=RuntimeError("boom")), 1.0)
    assert i.name == "unknown" and cost == 0 and "boom" in err
    seen = []
    i, _, err = classify("x", "en", _chat("eta", seen=seen), 0.0)
    assert i.name == "unknown" and not seen and "budget" in err
