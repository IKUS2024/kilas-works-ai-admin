"""Demo domain integration regression suite — Tests A-H from the request.

Run with:
    python3 test_demo_domain_integration.py
"""
import os
import json
from unittest.mock import patch

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

import _test_bootstrap  # noqa: E402,F401 — must run before `import app`, see _test_bootstrap.py

import app as appmod

FLASK_APP = appmod.app
FLASK_APP.testing = True
FLASK_APP.config["PROPAGATE_EXCEPTIONS"] = True
client = FLASK_APP.test_client()

sent_log = []


def reset_state():
    global sent_log
    sent_log = []
    appmod.customer_names.clear()
    appmod.conversations.clear()
    appmod.active_customer_context.clear()
    appmod.demo_link_offered.clear()


def fake_send_reply_bubbles(to, msg_id, text):
    for part in text.split("|||"):
        sent_log.append((to, part))
    return True, None


def fake_send_whatsapp_message(to, text):
    sent_log.append((to, text))
    return True, None


def customer_payload(number, text, msg_id):
    return {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": msg_id, "from": number, "type": "text", "text": {"body": text},
        }]}}]}]
    }


def send_customer_message(number, text, ai_reply, msg_id):
    with patch.object(appmod, "call_claude", return_value=ai_reply), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        return client.post("/webhook", data=json.dumps(customer_payload(number, text, msg_id)),
                            content_type="application/json")


# ---------------------------------------------------------------------------
# TEST A — demo.kilasworks.id / reaches/redirects to the existing demo.
# ---------------------------------------------------------------------------
def test_A_demo_domain_root_redirects_to_demo():
    resp = client.get("/", headers={"Host": "demo.kilasworks.id"})
    assert resp.status_code == 302, resp.status_code
    assert resp.headers.get("Location") == "/demo", resp.headers.get("Location")
    print("test_A_demo_domain_root_redirects_to_demo OK")


def test_A_health_check_unaffected_for_real_service_host():
    resp = client.get("/", headers={"Host": "kilas-works-ai-admin.onrender.com"})
    assert resp.status_code == 200
    assert resp.data == b"Kilas Works AI Admin - server jalan!", resp.data
    print("test_A_health_check_unaffected_for_real_service_host OK")


# ---------------------------------------------------------------------------
# TEST B — existing /demo still works, unduplicated.
# ---------------------------------------------------------------------------
def test_B_existing_demo_route_still_works():
    resp = client.get("/demo")
    assert resp.status_code == 200
    assert len(resp.data) > 500
    print("test_B_existing_demo_route_still_works OK")


def test_B_demo_api_route_still_registered():
    rules = [r.rule for r in FLASK_APP.url_map.iter_rules()]
    assert "/demo/api" in rules
    assert "/demo" in rules
    # Confirm no route DUPLICATION for "/" (would silently break one of the two).
    root_rules = [r for r in FLASK_APP.url_map.iter_rules() if r.rule == "/"]
    assert len(root_rules) == 1, f"BUG: multiple competing routes registered for '/': {root_rules}"
    print("test_B_demo_api_route_still_registered OK")


# ---------------------------------------------------------------------------
# TEST C — explicit demo request -> response contains the demo link.
# ---------------------------------------------------------------------------
def test_C_explicit_demo_request_contains_link():
    reset_state()
    number = "628900400001"
    ai_reply = "Bisa Kak. Kalau mau coba langsung, ada demo AI Admin di sini: https://demo.kilasworks.id"
    resp = send_customer_message(number, "ada demo AI Admin?", ai_reply, "wamid.C.1")
    assert resp.status_code == 200
    texts = [t for n, t in sent_log if n == number]
    assert any("https://demo.kilasworks.id" in t for t in texts)
    print("test_C_explicit_demo_request_contains_link OK")


def test_C_prompt_instructs_demo_offer_for_explicit_requests():
    prompt = appmod.SYSTEM_PROMPT
    assert "https://demo.kilasworks.id" in prompt
    assert "ada demo?" in prompt or "ada demo" in prompt
    print("test_C_prompt_instructs_demo_offer_for_explicit_requests OK")


# ---------------------------------------------------------------------------
# TEST D — "gimana cara kerja AI Admin?" -> demo may be offered naturally.
# ---------------------------------------------------------------------------
def test_D_how_it_works_question_prompt_allows_demo_offer():
    prompt = appmod.SYSTEM_PROMPT
    assert "gimana cara kerjanya" in prompt
    assert "PROAKTIF" in prompt
    print("test_D_how_it_works_question_prompt_allows_demo_offer OK")


def test_D_how_it_works_end_to_end_can_include_demo():
    reset_state()
    number = "628900400002"
    ai_reply = ("AI Admin balas otomatis based on data bisnis kamu. Biar kebayang, coba langsung di "
                "https://demo.kilasworks.id ya.")
    resp = send_customer_message(number, "gimana cara kerja AI Admin sih?", ai_reply, "wamid.D.1")
    assert resp.status_code == 200
    texts = [t for n, t in sent_log if n == number]
    assert any("https://demo.kilasworks.id" in t for t in texts)
    print("test_D_how_it_works_end_to_end_can_include_demo OK")


# ---------------------------------------------------------------------------
# TEST E — customer discussing Foto only -> AI Admin demo not randomly promoted.
# ---------------------------------------------------------------------------
def test_E_unrelated_service_prompt_instructs_no_random_promotion():
    prompt = appmod.SYSTEM_PROMPT
    assert "JANGAN asal nawarin demo di SETIAP obrolan" in prompt
    assert "Foto/Video/Website/Talent Management" in prompt
    print("test_E_unrelated_service_prompt_instructs_no_random_promotion OK")


def test_E_foto_conversation_end_to_end_no_demo_link():
    reset_state()
    number = "628900400003"
    ai_reply = "Boleh Kak, buat foto produk kita punya paket custom quote. Mau brief kebutuhannya dulu?"
    resp = send_customer_message(number, "mau tanya soal jasa foto produk", ai_reply, "wamid.E.1")
    assert resp.status_code == 200
    texts = [t for n, t in sent_log if n == number]
    assert not any("demo.kilasworks.id" in t for t in texts)
    print("test_E_foto_conversation_end_to_end_no_demo_link OK")


# ---------------------------------------------------------------------------
# TEST F — demo already offered -> bot does not repeatedly spam the link.
# ---------------------------------------------------------------------------
def test_F_demo_already_offered_note_appears_in_next_prompt():
    reset_state()
    number = "628900400004"
    appmod.demo_link_offered.add(number)
    prompt = appmod.build_customer_system_prompt(number)
    assert "SUDAH pernah dikasih" in prompt
    print("test_F_demo_already_offered_note_appears_in_next_prompt OK")


def test_F_demo_not_yet_offered_no_note():
    reset_state()
    number = "628900400005"
    prompt = appmod.build_customer_system_prompt(number)
    assert "SUDAH pernah dikasih" not in prompt
    print("test_F_demo_not_yet_offered_no_note OK")


def test_F_sending_demo_link_marks_customer_as_offered():
    reset_state()
    number = "628900400006"
    ai_reply = "Ini demo-nya Kak: https://demo.kilasworks.id"
    send_customer_message(number, "ada demo?", ai_reply, "wamid.F.1")
    assert number in appmod.demo_link_offered, \
        "BUG: sending the demo link must mark this customer as already-offered"
    print("test_F_sending_demo_link_marks_customer_as_offered OK")


# ---------------------------------------------------------------------------
# TEST G — tenant customer conversation never receives Kilas Works demo promotion.
# ---------------------------------------------------------------------------
def test_G_tenant_prompt_never_mentions_kilas_demo():
    assert "https://demo.kilasworks.id" not in appmod.TENANT_SYSTEM_PROMPT_BASE, \
        "BUG: a tenant's own customer-facing prompt must never advertise Kilas Works' own demo"
    print("test_G_tenant_prompt_never_mentions_kilas_demo OK")


def test_G_tenant_context_prompt_excludes_demo_note_even_if_offered_flag_somehow_set():
    """Defense in depth: even if demo_link_offered somehow contained a number that later turns out
    to be a tenant conversation, build_customer_system_prompt's tenant_context_block guard must
    still prevent the demo-offer note from ever appearing."""
    reset_state()
    number = "628900400007"
    appmod.demo_link_offered.add(number)  # simulate a stale/incorrect entry
    prompt = appmod.build_customer_system_prompt(number, tenant_context_block="\n\nKONTEKS BISNIS TENANT...\n")
    assert "SUDAH pernah dikasih" not in prompt
    assert "demo.kilasworks.id" not in prompt
    print("test_G_tenant_context_prompt_excludes_demo_note_even_if_offered_flag_somehow_set OK")


def test_G_demo_link_offered_never_populated_from_tenant_send_path():
    """The tracker is only ever written to from the Kilas-Works-own (tenant_context_block falsy)
    branch of the main send path — confirmed at the source level, since a live tenant webhook call
    in this test harness would require full tenant provisioning out of scope for this focused
    task."""
    import inspect
    source = inspect.getsource(appmod)
    idx = source.find('demo_link_offered.add(from_number)')
    assert idx != -1
    guard_snippet = source[max(0, idx - 300):idx]
    assert "not tenant_context_block" in guard_snippet
    print("test_G_demo_link_offered_never_populated_from_tenant_send_path OK")


# ---------------------------------------------------------------------------
# TEST H — landing page "Coba Demo AI Admin" points to https://demo.kilasworks.id.
# ---------------------------------------------------------------------------
def test_H_landing_page_demo_button_points_to_demo_subdomain():
    import re
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "landing-page-kilasworks.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    match = re.search(r'href="([^"]+)"[^>]*>\s*Coba Demo AI Admin', html)
    assert match, "Coba Demo AI Admin link not found"
    assert match.group(1) == "https://demo.kilasworks.id", match.group(1)
    assert "kilasworks.id/demo" not in html.replace("demo.kilasworks.id", ""), \
        "the obsolete kilasworks.id/demo link must no longer be the primary CTA"
    print("test_H_landing_page_demo_button_points_to_demo_subdomain OK")


if __name__ == "__main__":
    test_A_demo_domain_root_redirects_to_demo()
    test_A_health_check_unaffected_for_real_service_host()
    test_B_existing_demo_route_still_works()
    test_B_demo_api_route_still_registered()
    test_C_explicit_demo_request_contains_link()
    test_C_prompt_instructs_demo_offer_for_explicit_requests()
    test_D_how_it_works_question_prompt_allows_demo_offer()
    test_D_how_it_works_end_to_end_can_include_demo()
    test_E_unrelated_service_prompt_instructs_no_random_promotion()
    test_E_foto_conversation_end_to_end_no_demo_link()
    test_F_demo_already_offered_note_appears_in_next_prompt()
    test_F_demo_not_yet_offered_no_note()
    test_F_sending_demo_link_marks_customer_as_offered()
    test_G_tenant_prompt_never_mentions_kilas_demo()
    test_G_tenant_context_prompt_excludes_demo_note_even_if_offered_flag_somehow_set()
    test_G_demo_link_offered_never_populated_from_tenant_send_path()
    test_H_landing_page_demo_button_points_to_demo_subdomain()
    print("ALL DEMO DOMAIN INTEGRATION TESTS PASSED")
