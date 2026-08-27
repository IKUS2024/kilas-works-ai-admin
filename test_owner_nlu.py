import os
import json
from unittest.mock import patch

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

import app as appmod


def reset_state():
    appmod.customer_names.clear()
    appmod.conversations.clear()
    appmod.active_customer_context.clear()
    appmod.pending_owner_questions.clear()


# ---------- Test 1: parse_owner_send_command must NOT misfire on history questions ----------
def test_no_false_positive_send_command():
    reset_state()
    appmod.customer_names["628999900001"] = "JelajahVisa"
    cases = [
        "itu jelajah visa chat apa aja",
        "jelajah visa tadi ngomong apa",
        "caca terakhir chat apa?",
        "kimfong tadi nanya apa",
        "yang barusan chat siapa?",
        "itu tadi ngomong apa",
    ]
    for text in cases:
        result = appmod.parse_owner_send_command(text)
        assert result is None, f"FALSE POSITIVE send-command detected for: {text!r} -> {result}"
    print("test_no_false_positive_send_command OK")


# ---------- Test 2: pronoun-based send command still works ----------
def test_pronoun_send_still_works():
    reset_state()
    appmod.customer_names["628999900002"] = "Caca"
    result = appmod.parse_owner_send_command("balas dia bilang nanti gw hubungi")
    assert result is not None, "pronoun-based send command should still be detected"
    assert result["target_raw"].lower() == "dia"
    assert "nanti gw hubungi" in result["rest"]
    print("test_pronoun_send_still_works OK")


# ---------- Test 3: find_customers_by_name is space-insensitive ----------
def test_space_insensitive_name_matching():
    reset_state()
    appmod.customer_names["628999900003"] = "JelajahVisa"
    matches = appmod.find_customers_by_name("jelajah visa")
    assert len(matches) == 1, f"expected 1 match, got {matches}"
    assert matches[0][1] == "JelajahVisa"
    matches2 = appmod.find_customers_by_name("jelajah")
    assert len(matches2) == 1, f"expected 1 match, got {matches2}"
    print("test_space_insensitive_name_matching OK")


# ---------- Test 4: extract_mentioned_customer finds the right customer, ignores stopwords ----------
def test_extract_mentioned_customer():
    reset_state()
    appmod.customer_names["628999900004"] = "JelajahVisa"
    appmod.customer_names["628999900005"] = "Kimfong Wijaya"

    status, data, _ = appmod.extract_mentioned_customer("itu jelajah visa chat apa aja")
    assert status == "ok", (status, data)
    assert data == "628999900004"

    status2, data2, _ = appmod.extract_mentioned_customer("kimfong tadi nanya apa")
    assert status2 == "ok", (status2, data2)
    assert data2 == "628999900005"

    status3, data3, _ = appmod.extract_mentioned_customer("apa aja tadi")
    assert status3 == "none", (status3, data3)
    print("test_extract_mentioned_customer OK")


# ---------- Test 5: end-to-end webhook — the EXACT reported bug scenario ----------
def test_webhook_jelajahvisa_history_query_end_to_end():
    reset_state()
    number = "628999900006"
    appmod.customer_names[number] = "JelajahVisa"
    appmod.conversations[number] = [
        {"role": "user", "content": "Halo, mau tanya paket content dong"},
        {"role": "assistant", "content": "Halo! Boleh cerita dulu kebutuhan bisnisnya?"},
    ]
    appmod.active_customer_context[appmod.OWNER_WHATSAPP_NUMBER] = number

    client = appmod.app.test_client()
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": "wamid.nlu1", "from": appmod.OWNER_WHATSAPP_NUMBER, "type": "text",
            "text": {"body": "itu jelajah visa chat apa aja"},
        }]}}]}]
    }

    captured = {}

    def fake_call_claude_owner(owner_number, owner_message, pending_question, pending_customer_number, **kwargs):
        captured["pending_customer_number"] = pending_customer_number
        captured["pending_question"] = pending_question
        return "Dia baru nanya soal paket content kak."

    with patch.object(appmod, "call_claude_owner", side_effect=fake_call_claude_owner), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")

    assert resp.status_code == 200
    assert captured.get("pending_customer_number") == number, (
        f"Bot should resolve to JelajahVisa's number, got: {captured}"
    )
    print("test_webhook_jelajahvisa_history_query_end_to_end OK — resolved to JelajahVisa, NOT 'apa'")


# ---------- Test 6: ambiguous name -> ask, don't guess ----------
def test_ambiguous_mention_asks_not_guesses():
    reset_state()
    appmod.customer_names["628999900007"] = "Kimfong Wijaya"
    appmod.customer_names["628999900008"] = "Kimfong Tan"

    sent_log = []

    def fake_send(to, text):
        sent_log.append((to, text))
        return True, None

    client = appmod.app.test_client()
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": "wamid.nlu2", "from": appmod.OWNER_WHATSAPP_NUMBER, "type": "text",
            "text": {"body": "kimfong tadi nanya apa"},
        }]}}]}]
    }
    with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 200
    assert any("mirip" in t for _, t in sent_log), sent_log
    print("test_ambiguous_mention_asks_not_guesses OK")


if __name__ == "__main__":
    test_no_false_positive_send_command()
    test_pronoun_send_still_works()
    test_space_insensitive_name_matching()
    test_extract_mentioned_customer()
    test_webhook_jelajahvisa_history_query_end_to_end()
    test_ambiguous_mention_asks_not_guesses()
    print("ALL NLU TESTS PASSED")
