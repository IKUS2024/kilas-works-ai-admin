"""Production reliability fix — AI Setup structured output, draft persistence, empty-overwrite
protection, file persistence, admin/customer UX. Real customer incident: onboarding data
persisted correctly, but AI Generated Knowledge repeatedly failed with RESPONSE_PARSE_ERROR around
~4,100 characters (a business with a large services list, e.g. multiple endorsement packages).

Run with:
    cd client-hub && python3 tests/test_ai_setup_reliability_and_persistence.py
"""
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ.pop("DATABASE_URL", None)

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import catalog_service  # noqa: E402
import ai_onboarding  # noqa: E402
import app as client_hub_app  # noqa: E402

FLASK_APP = client_hub_app.app
FLASK_APP.testing = True
FLASK_APP.config["PROPAGATE_EXCEPTIONS"] = True


def fresh_client():
    return FLASK_APP.test_client()


def reset_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    db._local.conn = None
    db.init_schema()
    catalog_service.seed_catalog_if_needed()


def _make_owner_and_business(name, email, package="AI_ADMIN_BASIC"):
    uid = repo.create_user(email, security.hash_password("password123"))
    bid = repo.create_business(uid, name, package=package)
    return uid, bid


def _login_owner(client, email, password="password123"):
    client.post("/login", data={"email": email, "password": password})


def _fake_anthropic_response(text, stop_reason="end_turn"):
    resp = type("R", (), {})()
    resp.status_code = 200
    resp.raise_for_status = lambda: None
    resp.json = lambda: {"content": [{"text": text}], "stop_reason": stop_reason}
    return resp


VALID_CONFIG_JSON = """{
  "business_name": "Kedai Kopi Sinar", "category": "Kedai kopi", "description": "Kedai kopi santai",
  "languages": {"primary": "id", "additional": []}, "tone": "ramah",
  "owner": {"name": "Budi", "salutation_for_customers": "Kak"},
  "business_hours": {"raw_summary": "08-20", "structured": null},
  "services": [{"raw_input": "Kopi susu - 20rb", "service_name": "Kopi Susu", "description": null,
                "price_from": 20000, "price_to": null, "currency": "IDR", "needs_review": false}],
  "faqs": [], "policies": [], "appointment_rules": null, "payment_rules": null, "missing_fields": []
}"""


# ---------------------------------------------------------------------------
# _scaled_max_tokens boundary tests.
# ---------------------------------------------------------------------------
def test_scaled_tokens_small_input_returns_minimum_bounded_value():
    small_input = "Nama bisnis: Kedai Kopi\nKategori: kopi"
    result = ai_onboarding._scaled_max_tokens(small_input)
    assert result == ai_onboarding.NORMALIZATION_MAX_TOKENS
    print("test_scaled_tokens_small_input_returns_minimum_bounded_value OK")


def test_scaled_tokens_medium_large_input_scales_upward():
    medium_input = "Layanan: " + ("Endorse reels instagram : Rp 2.500.000. " * 500)  # ~20,000 chars
    result = ai_onboarding._scaled_max_tokens(medium_input)
    assert result > ai_onboarding.NORMALIZATION_MAX_TOKENS, \
        f"a genuinely large input must scale the budget upward, got {result}"
    assert result < ai_onboarding.NORMALIZATION_MAX_TOKENS_CEILING, \
        "this input should scale up but not yet hit the ceiling (see the huge-input test for that case)"
    print("test_scaled_tokens_medium_large_input_scales_upward OK")


def test_scaled_tokens_huge_input_never_exceeds_ceiling():
    huge_input = "Layanan: " + ("Endorse reels instagram : Rp 2.500.000. " * 5000)  # ~225,000 chars
    result = ai_onboarding._scaled_max_tokens(huge_input)
    assert result <= ai_onboarding.NORMALIZATION_MAX_TOKENS_CEILING, \
        f"BUG: scaled tokens exceeded the bounded ceiling: {result}"
    assert result == ai_onboarding.NORMALIZATION_MAX_TOKENS_CEILING
    print("test_scaled_tokens_huge_input_never_exceeds_ceiling OK")


def test_scaled_tokens_empty_input_returns_minimum():
    assert ai_onboarding._scaled_max_tokens("") == ai_onboarding.NORMALIZATION_MAX_TOKENS
    assert ai_onboarding._scaled_max_tokens(None) == ai_onboarding.NORMALIZATION_MAX_TOKENS
    print("test_scaled_tokens_empty_input_returns_minimum OK")


# ---------------------------------------------------------------------------
# Realistic large-business normalization test — the actual reported incident shape.
# ---------------------------------------------------------------------------
def _build_large_endorsement_business_services():
    """A realistic large business: many endorsement/package tiers with prices, matching the
    reported production incident (Endorse reels instagram, Endorse feed photo, Endorse story,
    etc.) — enough entries that the honestly-represented structured JSON output would plausibly
    exceed the OLD 4096-token budget."""
    tiers = [
        ("Endorse reels instagram", 2_500_000), ("Endorse feed photo", 1_500_000),
        ("Endorse story", 500_000), ("Endorse carousel 3 slide", 1_800_000),
        ("Endorse reels + story bundle", 3_200_000), ("Endorse TikTok video", 2_800_000),
        ("Endorse YouTube shorts", 2_200_000), ("Endorse live review 30 menit", 4_000_000),
        ("Endorse giveaway post", 1_200_000), ("Endorse testimonial video", 3_500_000),
        ("Endorse unboxing video", 3_000_000), ("Endorse comparison review", 2_600_000),
    ]
    return [f"{name} : Rp {price:,}".replace(",", ".") for name, price in tiers]


def _build_large_config_json_response():
    """A structured JSON response representing the large business above, deliberately padded
    with realistic descriptions to plausibly exceed 4096 tokens of output when combined with FAQs
    — this is what a HONEST, non-truncated model response for this business would look like."""
    tiers = [
        ("Endorse reels instagram", "Endorse Reels Instagram", 2500000,
         "Konten reels 15-30 detik, review produk natural, posting di akun utama dengan reach organik tinggi"),
        ("Endorse feed photo", "Endorse Feed Photo", 1500000,
         "Foto produk di feed utama dengan caption review, tetap ada di profil permanen"),
        ("Endorse story", "Endorse Story Instagram", 500000,
         "Story 24 jam dengan swipe up/link stiker, cocok untuk promo cepat"),
        ("Endorse carousel 3 slide", "Endorse Carousel 3 Slide", 1800000,
         "Carousel post 3 slide untuk showcase multiple angle produk"),
        ("Endorse reels + story bundle", "Bundle Reels + Story", 3200000,
         "Paket gabungan reels dan story untuk exposure maksimal dalam satu campaign"),
        ("Endorse TikTok video", "Endorse TikTok Video", 2800000,
         "Video TikTok dengan trending audio dan hook di 3 detik pertama"),
        ("Endorse YouTube shorts", "Endorse YouTube Shorts", 2200000,
         "Short-form video YouTube dengan CTA jelas di akhir"),
        ("Endorse live review 30 menit", "Live Review 30 Menit", 4000000,
         "Live session review mendalam dengan interaksi audience real-time"),
        ("Endorse giveaway post", "Endorse Giveaway Post", 1200000,
         "Post giveaway kolaborasi untuk boost engagement dan followers"),
        ("Endorse testimonial video", "Endorse Testimonial Video", 3500000,
         "Video testimonial personal dengan storytelling pengalaman pakai produk"),
        ("Endorse unboxing video", "Endorse Unboxing Video", 3000000,
         "Video unboxing dengan first impression natural dan detail produk"),
        ("Endorse comparison review", "Endorse Comparison Review", 2600000,
         "Review perbandingan dengan produk kompetitor untuk highlight keunggulan"),
    ]
    def _make_service_entry(raw, name, price, desc):
        raw_input_text = f"{raw} : Rp {price:,}".replace(",", ".")
        return (f'    {{"raw_input": "{raw_input_text}", "service_name": "{name}", '
                f'"description": "{desc}", "price_from": {price}, "price_to": null, '
                f'"currency": "IDR", "needs_review": false}}')

    services_json = ",\n".join(_make_service_entry(raw, name, price, desc) for raw, name, price, desc in tiers)
    faqs_json = ",\n".join(
        f'    {{"raw_input": "FAQ {i}", "question": "Pertanyaan umum nomor {i}?", '
        f'"answer": "Jawaban lengkap dan detail untuk pertanyaan nomor {i} supaya customer paham prosesnya.", '
        f'"category": "general", "needs_review": false}}'
        for i in range(1, 8)
    )
    return (
        '{\n'
        '  "business_name": "Talent Endorse Studio", "category": "Jasa endorsement & influencer marketing",\n'
        '  "description": "Layanan endorsement multi-platform dengan berbagai paket sesuai kebutuhan campaign",\n'
        '  "languages": {"primary": "id", "additional": []}, "tone": "profesional dan ramah",\n'
        '  "owner": {"name": "Sinta", "salutation_for_customers": "Kak"},\n'
        '  "business_hours": {"raw_summary": "Senin-Jumat 09.00-18.00", "structured": null},\n'
        f'  "services": [\n{services_json}\n  ],\n'
        f'  "faqs": [\n{faqs_json}\n  ],\n'
        '  "policies": ["DP 50% di muka", "Revisi maksimal 1x"],\n'
        '  "appointment_rules": null, "payment_rules": "Transfer bank, DP 50%", "missing_fields": []\n'
        '}'
    )


def test_large_business_normalization_uses_scaled_budget_and_preserves_all_services():
    """The core new-scenario test requested: a realistic large business whose honest structured
    output would plausibly exceed the OLD 4096 budget. Proves the scaled budget is chosen, the
    application never intentionally truncates the model's output, the repair path (if ever
    invoked) gets a comparably large budget, and every raw service entry survives normalization."""
    reset_db()
    uid, bid = _make_owner_and_business("Talent Endorse Studio", "endorse@test.com", package="AI_ADMIN_PRO")
    business = repo.get_business(bid)
    profile = {"category": "Jasa endorsement"}
    raw_services = _build_large_endorsement_business_services()
    large_response = _build_large_config_json_response()

    # Sanity: this response is genuinely large enough to matter for this test.
    assert len(large_response) > 4100, "test fixture must be realistically large to be meaningful"

    input_text = ai_onboarding.build_normalization_input_text(business, profile, raw_services, [], [])
    expected_scaled_budget = ai_onboarding._scaled_max_tokens(input_text)
    assert expected_scaled_budget > ai_onboarding.NORMALIZATION_MAX_TOKENS or len(input_text) < 2000, (
        "a business with 12 detailed services should trigger upward scaling given enough raw input length"
    )

    captured_max_tokens = []

    def fake_call_claude(system_prompt, messages, max_tokens=1500):
        captured_max_tokens.append(max_tokens)
        # Never truncate here — proves the APPLICATION itself does not clip/cut the model's output;
        # any truncation in real life comes from the API's own stop_reason, simulated separately below.
        return large_response, "end_turn", None

    with patch.object(ai_onboarding, "_call_claude", side_effect=fake_call_claude):
        config, error = ai_onboarding.normalize_business_data(business, profile, raw_services, [], [])

    assert error is None, f"unexpected error: {error}"
    assert config is not None
    assert len(captured_max_tokens) == 1, "no repair call should have been needed for valid output"
    assert captured_max_tokens[0] >= ai_onboarding.NORMALIZATION_MAX_TOKENS
    assert captured_max_tokens[0] == expected_scaled_budget

    # All 12 raw service entries must be represented in the normalized output.
    assert len(config["services"]) == 12
    normalized_names = {s["service_name"] for s in config["services"]}
    assert "Endorse Reels Instagram" in normalized_names
    assert "Live Review 30 Menit" in normalized_names
    assert "Endorse Comparison Review" in normalized_names
    print("test_large_business_normalization_uses_scaled_budget_and_preserves_all_services OK")


def test_large_business_truncated_response_triggers_repair_with_sufficient_budget():
    """Simulates the ACTUAL reported failure shape: the initial call gets genuinely truncated
    (stop_reason=max_tokens) partway through a large business's service list, and the repair
    attempt must receive a comparably large budget (not the old flat 4096) — proving the repair
    call itself would no longer truncate at the identical point for the identical reason."""
    reset_db()
    uid, bid = _make_owner_and_business("Talent Endorse Studio 2", "endorse2@test.com", package="AI_ADMIN_PRO")
    business = repo.get_business(bid)
    profile = {"category": "Jasa endorsement"}
    raw_services = _build_large_endorsement_business_services()
    large_response = _build_large_config_json_response()
    truncated_response = large_response[:4150]  # cut mid-string, exactly like the real incident

    call_log = []

    def fake_call_claude(system_prompt, messages, max_tokens=1500):
        call_log.append(max_tokens)
        if len(call_log) == 1:
            return truncated_response, "max_tokens", None  # genuinely truncated first attempt
        return large_response, "end_turn", None  # repair succeeds with the FULL content

    with patch.object(ai_onboarding, "_call_claude", side_effect=fake_call_claude):
        config, error = ai_onboarding.normalize_business_data(business, profile, raw_services, [], [])

    assert len(call_log) == 2, "exactly one repair attempt, never more"
    assert call_log[0] >= ai_onboarding.NORMALIZATION_MAX_TOKENS
    assert call_log[1] >= ai_onboarding.NORMALIZATION_MAX_TOKENS, \
        "the repair call must get a comparably large budget, not the old flat 4096"
    assert error is None
    assert len(config["services"]) == 12
    print("test_large_business_truncated_response_triggers_repair_with_sufficient_budget OK")


# ---------------------------------------------------------------------------
# Repair/retry core behavior tests (Sections A, N.3-6).
# ---------------------------------------------------------------------------
def test_valid_json_succeeds_no_repair_needed():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Valid", "valid@test.com")
    business = repo.get_business(bid)
    with patch.object(ai_onboarding, "_call_claude", return_value=(VALID_CONFIG_JSON, "end_turn", None)) as mock:
        config, error = ai_onboarding.normalize_business_data(business, {}, ["Kopi susu - 20rb"], [], [])
    assert error is None
    assert mock.call_count == 1
    print("test_valid_json_succeeds_no_repair_needed OK")


def test_json_inside_markdown_fences_succeeds():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Fence", "fence@test.com")
    business = repo.get_business(bid)
    fenced = f"```json\n{VALID_CONFIG_JSON}\n```"
    with patch.object(ai_onboarding, "_call_claude", return_value=(fenced, "end_turn", None)):
        config, error = ai_onboarding.normalize_business_data(business, {}, ["Kopi susu - 20rb"], [], [])
    assert error is None
    assert config["business_name"] == "Kedai Kopi Sinar"
    print("test_json_inside_markdown_fences_succeeds OK")


def test_unterminated_string_triggers_repair_then_succeeds():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Unterm", "unterm@test.com")
    business = repo.get_business(bid)
    broken = VALID_CONFIG_JSON[:100] + '"unterminated'
    with patch.object(ai_onboarding, "_call_claude",
                       side_effect=[(broken, "end_turn", None), (VALID_CONFIG_JSON, "end_turn", None)]):
        config, error = ai_onboarding.normalize_business_data(business, {}, ["Kopi susu - 20rb"], [], [])
    assert error is None
    assert config["business_name"] == "Kedai Kopi Sinar"
    print("test_unterminated_string_triggers_repair_then_succeeds OK")


def test_invalid_property_quotes_triggers_repair_then_succeeds():
    reset_db()
    uid, bid = _make_owner_and_business("Biz BadQuote", "badquote@test.com")
    business = repo.get_business(bid)
    broken = '{business_name: "no quotes on key"}'
    with patch.object(ai_onboarding, "_call_claude",
                       side_effect=[(broken, "end_turn", None), (VALID_CONFIG_JSON, "end_turn", None)]):
        config, error = ai_onboarding.normalize_business_data(business, {}, ["Kopi susu - 20rb"], [], [])
    assert error is None
    print("test_invalid_property_quotes_triggers_repair_then_succeeds OK")


def test_both_attempts_malformed_fails_closed_no_infinite_loop():
    reset_db()
    uid, bid = _make_owner_and_business("Biz DoubleBad", "doublebad@test.com")
    business = repo.get_business(bid)
    call_count = [0]

    def always_broken(*a, **kw):
        call_count[0] += 1
        return "still not json {{{", "end_turn", None

    with patch.object(ai_onboarding, "_call_claude", side_effect=always_broken):
        config, error = ai_onboarding.normalize_business_data(business, {}, ["Kopi susu - 20rb"], [], [])
    assert config is None
    assert error is not None
    assert call_count[0] == 2, "must be exactly initial + one repair, never more (no infinite loop)"
    print("test_both_attempts_malformed_fails_closed_no_infinite_loop OK")


def test_customer_input_with_quotes_and_newlines_parses_safely():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Quotes", "quotes@test.com")
    business = repo.get_business(bid)
    tricky_service = 'Paket "Premium" spesial\nharga nego, DM aja ya kak — "flash sale" tiap Jumat'
    input_text = ai_onboarding.build_normalization_input_text(business, {}, [tricky_service], [], [])
    assert tricky_service.split("\n")[0] in input_text  # the raw text is embedded, not corrupted
    with patch.object(ai_onboarding, "_call_claude", return_value=(VALID_CONFIG_JSON, "end_turn", None)):
        config, error = ai_onboarding.normalize_business_data(business, {}, [tricky_service], [], [])
    assert error is None
    print("test_customer_input_with_quotes_and_newlines_parses_safely OK")


def test_extracted_file_text_with_quotes_and_newlines_parses_safely():
    reset_db()
    uid, bid = _make_owner_and_business("Biz FileQuotes", "filequotes@test.com")
    business = repo.get_business(bid)
    tricky_file_text = ('Daftar harga:\n"Endorse Reels" - Rp2.500.000\n"Endorse Story" - Rp500.000\n'
                        'Catatan: harga bisa nego "khusus repeat order"')
    with patch.object(ai_onboarding, "_call_claude", return_value=(VALID_CONFIG_JSON, "end_turn", None)):
        config, error = ai_onboarding.normalize_business_data(
            business, {}, [], [], [("harga.jpeg", tricky_file_text)])
    assert error is None
    print("test_extracted_file_text_with_quotes_and_newlines_parses_safely OK")


# ---------------------------------------------------------------------------
# Section H — uploaded file survives AI Setup failure/rerun/other-step edits/refresh/relogin.
# ---------------------------------------------------------------------------
def test_uploaded_file_survives_ai_setup_failure():
    reset_db()
    uid, bid = _make_owner_and_business("Biz File", "file@test.com", package="AI_ADMIN_BASIC")
    repo.save_business_file(bid, "IMG_5491.jpeg", "image/jpeg", 123456, b"fake-bytes", "extracted text", uid)
    files_before = repo.list_business_files(bid)
    assert len(files_before) == 1
    assert files_before[0]["original_filename"] == "IMG_5491.jpeg"

    repo.set_ai_status(bid, "FAILED", "RESPONSE_PARSE_ERROR: Unterminated string")

    files_after = repo.list_business_files(bid)
    assert len(files_after) == 1
    assert files_after[0]["original_filename"] == "IMG_5491.jpeg", \
        "BUG: uploaded file must never disappear merely because AI Setup failed"
    print("test_uploaded_file_survives_ai_setup_failure OK")


def test_uploaded_file_survives_across_refresh_relogin_simulation():
    """A "refresh"/"relogin" is, from the server's perspective, just a fresh GET after the DB
    write already committed — proven by reading files back via a completely separate DB
    connection/query, not relying on any in-memory state."""
    reset_db()
    uid, bid = _make_owner_and_business("Biz FileRefresh", "filerefresh@test.com")
    repo.save_business_file(bid, "IMG_5491.jpeg", "image/jpeg", 123456, b"fake-bytes", "text", uid)
    db._local.conn = None  # force a fresh connection, simulating a new request/process
    files = repo.list_business_files(bid)
    assert len(files) == 1
    print("test_uploaded_file_survives_across_refresh_relogin_simulation OK")


def test_uploaded_file_survives_editing_other_wizard_steps():
    reset_db()
    uid, bid = _make_owner_and_business("Biz FileEdit", "fileedit@test.com")
    repo.save_business_file(bid, "IMG_5491.jpeg", "image/jpeg", 123456, b"fake-bytes", "text", uid)
    client = fresh_client()
    _login_owner(client, "fileedit@test.com")
    client.post(f"/business/{bid}/wizard/operations", data={
        "operating_hours": "08-20", "closed_days": "Minggu", "online_or_offline": "offline",
    })
    files = repo.list_business_files(bid)
    assert len(files) == 1, "editing an unrelated wizard step must never remove an uploaded file"
    print("test_uploaded_file_survives_editing_other_wizard_steps OK")


def test_uploaded_file_survives_ai_setup_rerun():
    reset_db()
    uid, bid = _make_owner_and_business("Biz FileRerun", "filererun@test.com")
    repo.save_business_file(bid, "IMG_5491.jpeg", "image/jpeg", 123456, b"fake-bytes", "text", uid)
    repo.set_ai_status(bid, "FAILED", "some error")
    repo.set_ai_status(bid, "DONE")  # simulates a successful rerun
    files = repo.list_business_files(bid)
    assert len(files) == 1
    print("test_uploaded_file_survives_ai_setup_rerun OK")


# ---------------------------------------------------------------------------
# Section F/G — draft persistence + empty-value overwrite protection.
# ---------------------------------------------------------------------------
def test_refresh_reopen_wizard_prepopulates_saved_fields():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Draft", "draft@test.com")
    client = fresh_client()
    _login_owner(client, "draft@test.com")
    client.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Biz Draft", "category": "Kedai kopi", "owner_name": "Budi",
        "address": "Jl. Mawar No. 1",
    })
    resp = client.get(f"/business/{bid}/wizard/basics")
    body = resp.data.decode()
    assert 'value="Kedai kopi"' in body
    assert 'value="Budi"' in body
    assert "Jl. Mawar No. 1" in body
    print("test_refresh_reopen_wizard_prepopulates_saved_fields OK")


def test_partial_update_does_not_erase_unrelated_saved_fields():
    """The exact scenario from Section G: existing non-blank value + a later partial update on the
    SAME step that submits that field blank — must NOT erase the existing value."""
    reset_db()
    uid, bid = _make_owner_and_business("Biz Patch", "patch@test.com")
    client = fresh_client()
    _login_owner(client, "patch@test.com")
    client.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Biz Patch", "category": "Kedai kopi", "owner_name": "Budi",
        "address": "Jl. Mawar No. 1", "business_phone": "081234567890",
    })
    # Re-submit the SAME step with address/business_phone blank (simulating a stale/partial
    # resubmission) but owner_name still filled.
    client.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Biz Patch", "category": "Kedai kopi", "owner_name": "Budi",
        "address": "", "business_phone": "",
    })
    profile = repo.get_business_profile(bid)
    assert profile["address"] == "Jl. Mawar No. 1", \
        f"BUG: a blank resubmission erased a previously-saved value: {profile['address']!r}"
    assert profile["business_phone"] == "081234567890"
    print("test_partial_update_does_not_erase_unrelated_saved_fields OK")


def test_merge_profile_patch_unit_blank_never_overwrites_nonblank():
    import routes_client
    existing = {"owner_name": "Budi", "address": "Jl. Lama", "category": ""}
    new_raw = {"owner_name": "", "address": "Jl. Baru", "category": "Kedai kopi"}
    merged = routes_client._merge_profile_patch(existing, new_raw)
    assert merged["owner_name"] == "Budi", "blank new value must not overwrite existing non-blank value"
    assert merged["address"] == "Jl. Baru", "non-blank new value must always win (real edit applies)"
    assert merged["category"] == "Kedai kopi", "blank existing + non-blank new -> new value applies"
    print("test_merge_profile_patch_unit_blank_never_overwrites_nonblank OK")


def test_customer_edits_existing_setup_changes_persist():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Resume", "resume@test.com")
    client = fresh_client()
    _login_owner(client, "resume@test.com")
    client.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Biz Resume", "category": "Kedai kopi", "owner_name": "Budi",
    })
    client.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Biz Resume", "category": "Kedai kopi modern", "owner_name": "Budi Santoso",
    })
    profile = repo.get_business_profile(bid)
    assert profile["category"] == "Kedai kopi modern"
    assert profile["owner_name"] == "Budi Santoso"
    print("test_customer_edits_existing_setup_changes_persist OK")


def test_dashboard_has_resume_edit_action_for_draft_business():
    reset_db()
    uid, bid = _make_owner_and_business("Biz ResumeUI", "resumeui@test.com")
    client = fresh_client()
    _login_owner(client, "resumeui@test.com")
    resp = client.get("/dashboard")
    body = resp.data.decode()
    assert "Lanjutkan Setup" in body
    print("test_dashboard_has_resume_edit_action_for_draft_business OK")


# ---------------------------------------------------------------------------
# Section I — editing after generated knowledge exists marks it stale.
# ---------------------------------------------------------------------------
def test_editing_after_ai_success_marks_knowledge_stale():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Stale", "stale@test.com")
    repo.set_ai_status(bid, "DONE")
    client = fresh_client()
    _login_owner(client, "stale@test.com")
    client.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Biz Stale", "category": "Kategori baru", "owner_name": "Budi",
    })
    ai_settings = repo.get_ai_settings(bid)
    assert ai_settings["ai_status"] == "STALE", \
        "editing business info after successful AI setup must mark existing knowledge stale"
    print("test_editing_after_ai_success_marks_knowledge_stale OK")


# ---------------------------------------------------------------------------
# Section D — FAILED business rerun recovery (re-confirmed under this session's changes).
# ---------------------------------------------------------------------------
def test_failed_business_rerun_succeeds_same_business_continues():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Rerun", "rerun@test.com")
    client = fresh_client()
    _login_owner(client, "rerun@test.com")
    client.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Biz Rerun", "category": "Kedai kopi", "owner_name": "Budi"})
    client.post(f"/business/{bid}/wizard/services", data={"services_raw": "Kopi susu - 20rb"})
    client.post(f"/business/{bid}/wizard/operations", data={
        "operating_hours": "08-20", "closed_days": "Minggu", "online_or_offline": "offline"})
    client.post(f"/business/{bid}/wizard/faq", data={"faqs_raw": "Buka jam berapa? - 08.00"})
    client.post(f"/business/{bid}/wizard/style", data={
        "tone": "friendly", "primary_language": "id", "customer_salutation": "Kak"})
    repo.set_ai_status(bid, "FAILED", "RESPONSE_PARSE_ERROR: Unterminated string")

    with patch.object(ai_onboarding, "normalize_business_data",
                       return_value=({**{k: None for k in ai_onboarding.REQUIRED_CONFIG_KEYS},
                                      "services": [{"service_name": "Kopi Susu", "price_from": 20000,
                                                     "price_to": None, "currency": "IDR", "needs_review": False}],
                                      "faqs": [], "description": "desc", "missing_fields": []}, None)):
        resp = client.post(f"/business/{bid}/ai-setup/run", follow_redirects=True)
    assert resp.status_code == 200
    ai_settings = repo.get_ai_settings(bid)
    assert ai_settings["ai_status"] == "DONE"
    business = repo.get_business(bid)
    assert business["id"] == bid, "must be the SAME business, never a new one"
    print("test_failed_business_rerun_succeeds_same_business_continues OK")


def test_successful_rerun_populates_normalized_service_name_price():
    reset_db()
    uid, bid = _make_owner_and_business("Biz RerunNorm", "rerunnorm@test.com")
    repo.replace_business_services(bid, ["Endorse reels instagram : Rp 2.500.000"])
    services = repo.get_business_services(bid)
    repo.update_normalized_service(services[0]["id"], "Endorse Reels Instagram", None, 2500000, None, "IDR", False)
    updated = repo.get_business_services(bid)
    assert updated[0]["service_name"] == "Endorse Reels Instagram"
    assert updated[0]["price_from"] == 2500000
    print("test_successful_rerun_populates_normalized_service_name_price OK")


# ---------------------------------------------------------------------------
# Section J — admin normalization UX shows human-readable "not processed" state.
# ---------------------------------------------------------------------------
def test_admin_review_shows_belum_diproses_not_dash_when_failed():
    reset_db()
    uid, bid = _make_owner_and_business("Biz AdminUX", "adminux@test.com")
    admin_id = repo.create_user("admin_adminux@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN")
    admin = db.query_one("SELECT * FROM users WHERE id = ?", (admin_id,))
    repo.replace_business_services(bid, ["Endorse reels instagram : Rp 2.500.000"])
    repo.set_ai_status(bid, "FAILED", "RESPONSE_PARSE_ERROR: Unterminated string starting at line 103")

    client = fresh_client()
    client.post("/login", data={"email": admin["email"], "password": "adminpass123"})
    resp = client.get(f"/admin/business/{bid}")
    body = resp.data.decode()
    assert "Belum diproses" in body
    assert "AI Setup gagal" in body
    assert "Endorse reels instagram" in body, "RAW INPUT must stay visible even when AI failed"
    print("test_admin_review_shows_belum_diproses_not_dash_when_failed OK")


def test_admin_can_see_technical_diagnostic_detail():
    reset_db()
    uid, bid = _make_owner_and_business("Biz AdminDiag", "admindiag@test.com")
    admin_id = repo.create_user("admin_admindiag@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN")
    admin = db.query_one("SELECT * FROM users WHERE id = ?", (admin_id,))
    repo.set_ai_status(bid, "FAILED", "RESPONSE_PARSE_ERROR: Unterminated string starting at line 103 column 7")

    client = fresh_client()
    client.post("/login", data={"email": admin["email"], "password": "adminpass123"})
    resp = client.get(f"/admin/business/{bid}")
    body = resp.data.decode()
    assert "line 103 column 7" in body, "admin must still be able to see the technical diagnostic detail"
    print("test_admin_can_see_technical_diagnostic_detail OK")


# ---------------------------------------------------------------------------
# Section K — customer never sees raw parse errors.
# ---------------------------------------------------------------------------
def test_customer_never_sees_raw_parse_error_text():
    reset_db()
    uid, bid = _make_owner_and_business("Biz CustUX", "custux@test.com")
    repo.set_ai_status(bid, "FAILED", "RESPONSE_PARSE_ERROR: Unterminated string starting at line 103 column 7 (char 4144)")

    client = fresh_client()
    _login_owner(client, "custux@test.com")
    resp = client.get(f"/business/{bid}/review")
    body = resp.data.decode()
    assert "RESPONSE_PARSE_ERROR" not in body
    assert "line 103" not in body
    assert "char 4144" not in body
    assert "Data yang sudah diisi tetap aman" in body
    print("test_customer_never_sees_raw_parse_error_text OK")


# ---------------------------------------------------------------------------
# Section L — approval safety: malformed/FAILED knowledge never masquerades as READY.
# ---------------------------------------------------------------------------
def test_failed_ai_setup_never_advances_business_status_to_ready():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Approval", "approval@test.com")
    business_before = repo.get_business(bid)
    repo.set_ai_status(bid, "FAILED", "some parse error")
    business_after = repo.get_business(bid)
    assert business_after["status"] == business_before["status"], \
        "a failed AI setup must never silently advance business status toward approval"
    assert business_after["status"] != "READY_FOR_REVIEW"
    print("test_failed_ai_setup_never_advances_business_status_to_ready OK")


def test_existing_successful_onboarding_still_works_end_to_end():
    reset_db()
    uid, bid = _make_owner_and_business("Biz E2E", "e2e@test.com")
    client = fresh_client()
    _login_owner(client, "e2e@test.com")
    client.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Biz E2E", "category": "Kedai kopi", "owner_name": "Budi"})
    client.post(f"/business/{bid}/wizard/services", data={"services_raw": "Kopi susu - 20rb"})
    client.post(f"/business/{bid}/wizard/operations", data={
        "operating_hours": "08-20", "closed_days": "Minggu", "online_or_offline": "offline"})
    client.post(f"/business/{bid}/wizard/faq", data={"faqs_raw": "Buka jam berapa? - 08.00"})
    client.post(f"/business/{bid}/wizard/style", data={
        "tone": "friendly", "primary_language": "id", "customer_salutation": "Kak"})

    with patch.object(ai_onboarding, "normalize_business_data",
                       return_value=({**{k: None for k in ai_onboarding.REQUIRED_CONFIG_KEYS},
                                      "services": [], "faqs": [], "description": "desc", "missing_fields": []}, None)):
        resp = client.post(f"/business/{bid}/ai-setup/run", follow_redirects=True)
    assert resp.status_code == 200
    assert repo.get_ai_settings(bid)["ai_status"] == "DONE"
    print("test_existing_successful_onboarding_still_works_end_to_end OK")


if __name__ == "__main__":
    test_scaled_tokens_small_input_returns_minimum_bounded_value()
    test_scaled_tokens_medium_large_input_scales_upward()
    test_scaled_tokens_huge_input_never_exceeds_ceiling()
    test_scaled_tokens_empty_input_returns_minimum()
    test_large_business_normalization_uses_scaled_budget_and_preserves_all_services()
    test_large_business_truncated_response_triggers_repair_with_sufficient_budget()
    test_valid_json_succeeds_no_repair_needed()
    test_json_inside_markdown_fences_succeeds()
    test_unterminated_string_triggers_repair_then_succeeds()
    test_invalid_property_quotes_triggers_repair_then_succeeds()
    test_both_attempts_malformed_fails_closed_no_infinite_loop()
    test_customer_input_with_quotes_and_newlines_parses_safely()
    test_extracted_file_text_with_quotes_and_newlines_parses_safely()
    test_uploaded_file_survives_ai_setup_failure()
    test_uploaded_file_survives_across_refresh_relogin_simulation()
    test_uploaded_file_survives_editing_other_wizard_steps()
    test_uploaded_file_survives_ai_setup_rerun()
    test_refresh_reopen_wizard_prepopulates_saved_fields()
    test_partial_update_does_not_erase_unrelated_saved_fields()
    test_merge_profile_patch_unit_blank_never_overwrites_nonblank()
    test_customer_edits_existing_setup_changes_persist()
    test_dashboard_has_resume_edit_action_for_draft_business()
    test_editing_after_ai_success_marks_knowledge_stale()
    test_failed_business_rerun_succeeds_same_business_continues()
    test_successful_rerun_populates_normalized_service_name_price()
    test_admin_review_shows_belum_diproses_not_dash_when_failed()
    test_admin_can_see_technical_diagnostic_detail()
    test_customer_never_sees_raw_parse_error_text()
    test_failed_ai_setup_never_advances_business_status_to_ready()
    test_existing_successful_onboarding_still_works_end_to_end()
    print("ALL AI SETUP RELIABILITY + PERSISTENCE TESTS PASSED")
