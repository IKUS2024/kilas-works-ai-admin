# Official Links Light Patch

Baseline origin/main setelah fetch: `6c39951e911089e6c561da218cb3246684d050d1`
Final local commit: `e63536090f9688bcf14ad477aca01f4c2ced953a`
Branch: `fix/official-links-sales-cta-tenant-parity`
Satu commit lokal; tidak push/deploy. Worktree sebelumnya tidak diubah.

## Perubahan

Pure helper official_link_routing.py memisahkan klasifikasi dari resolusi URL. Regex/string matching, input classifier <=240 karakter, history hanya untuk follow-up: maksimal 6 turn terakhir x600 karakter; tidak ada AI classifier, summarizer, retry atau panggilan model tambahan. Resource: website, demo, Instagram, Client Hub, catalog. Request multi-resource atau kompleks yang tidak cocok grammar dibiarkan pada jalur existing, tanpa classifier AI baru.

Owner platform: obvious official-link requests dijawab sebelum send-target interpretation/Claude. Kata 'kirim' ke sini tidak lagi dianggap target customer. Perintah dengan target customer dan catalog-send tetap memakai jalur lama. Link follow-up owner mengikuti recent resource. Semua URL platform dari repo.get_official_links(), tidak diduplikasi. Failure settings mengembalikan unavailable tanpa raw exception/secret. Jawaban tidak mengklaim ada portfolio khusus/Drive folder. Fallback owner mendapat authority instruction dan source links singkat hanya untuk query link-relevant, bukan prompt permanen setiap chat.

Customer platform: direct links zero-LLM; generic follow-up memilih satu resource relevan, default website. Tidak lagi mengirim website+catalog+IG bersamaan. Exploratory request boleh mendapat website; demo hanya permintaan demo/bot eksplisit atau trial dengan konteks Kilas Brain. Pertanyaan Content tidak disisipi demo. Purchase intake tetap berjalan lebih dahulu, sehingga ready-to-buy Brain tetap menuju Setup Awal, bukan demo. Alias customer catalog dan app-link lama dipertahankan.

## Catalog dan scope yang dilindungi

Fungsi send_catalog_pdf, get_catalog_media_id dan _get_static_catalog_pdf_path_safe identik secara AST dengan baseline. Regresi pengiriman owner self/customer serta byte static PDF lulus. Tidak ada perubahan file PDF, konten/harga catalog, single-plan499k, payment/order implementation, schema/migration0026, Meta billing, model, compact_history, landing-page HTML/design atau Render ENV. Tidak ada migration, dependency production, atau ENV baru.

## Tenant parity

Resolved tenant memakai classifier sama tetapi tidak pernah membaca platform settings, harga/catalog Kilas Works atau link tenant lain. Schema Knowledge Setup yang tersedia belum memiliki field official website/demo/Instagram/app/catalog terstruktur. Runtime tenant dengan resource yang diminta mendapat 'Link tersebut belum tersedia di profil bisnis ini. Silakan hubungi tim bisnis.' Tidak menambang full config/raw knowledge, tidak menebak domain, dan tidak fallback ke Kilas Works. Pure resolver dapat menerima dictionary URL milik tenant saja; URL scheme/host/credential/whitespace divalidasi.

Batasan yang disengaja: mengaktifkan link tenant riil nantinya membutuhkan field/link mapping yang tenant-owned, authorized dan dihubungkan ke resolver. Light patch ini tidak membuat schema atau admin editor baru, dan belum mengambil URL dari FAQ/raw knowledge. Ini bukan blocker deployment patch; perilaku unavailable adalah fallback aman yang diminta task.

## Tes dan biaya

16/16 file targeted/regression lulus setelah targeted reruns; termasuk 14 kasus baru di test_official_links_light.py dan 23 kasus existing catalog UX. Provider mock assert_not_called untuk direct owner/customer/tenant links. Python offline sitecustomize memblokir jaringan; tidak ada paid API call. Jalur model normal, compact history dan retry policy existing tetap. Normal non-link prompt tidak bertambah; link kompleks owner mendapat block kecil query-gated. Test report terpisah merinci file.

## Deployment manual

Overlay kelima file source/test final pada baseline yang benar. Tidak perlu migration atau ENV baru. Kedua laporan hanya dokumentasi export, tidak membuat commit kedua. Operator dapat deploy secara manual setelah review; tidak ada deploy/push dilakukan oleh task. Tidak ada live WhatsApp smoke test atau pengiriman nyata selama tes.

## File berubah

- app.py
- client-hub/tests/test_business_sales_upgrade.py
- client-hub/tests/test_ux_catalog_final.py
- official_link_routing.py
- test_official_links_light.py

ZIP juga berisi OFFICIAL_LINKS_LIGHT_PATCH_REPORT.md dan OFFICIAL_LINKS_LIGHT_TEST_REPORT.md. Full file contents diambil dari commit final; tidak ada unchanged source, DB, env, cache, media atau secrets.
