# Rilis final — arsitektur dan audit implementasi

Rilis melanjutkan Phase 6C `b8b22046d02d150c84c059250aaaf56170f4f280`. Phase 6A/6B/6C dipertahankan sebagai commit asli; semua perubahan rilis baru berada di `client-hub/**`. Root Brain/Meta/WhatsApp dan harga Brain Rp499.000 tidak diubah. Hash final dan parent dihasilkan setelah commit pada metadata ZIP.

## Pemilik kemampuan

| Kemampuan | Pemilik yang tetap authoritative |
|---|---|
| Ledger integer IDR, akun/kategori, invoice/payment, laporan, recurring | `finance_service.py`, Finance 1A–3 |
| Pertanyaan read-only | Analyst 4A; deterministic facts server |
| Draft teks, signed review dan confirmation | Operator 4B/4C |
| Collections, public signed document | Finance 5AB/5C |
| Struk gambar/PDF, review, managed FINANCE_RECEIPT | Receipt 6A dan isolated PDF parser |
| Mutasi CSV/PDF/gambar, review/open/match/post/ignore | Bank 6B |
| Router enum, clarification, handoff transient | Assistant 6C; tidak ada execution engine baru |
| Pilihan produk dan onboarding | `product_flow.py`, `routes_products.py`; auth existing |
| Hak Finance, trial, expiry | `finance_entitlements.py`; enforcement route + business write lock |
| Tagihan langganan Finance dan manual verification | `finance_subscription.py`; store terpisah Brain/customer invoice |

Pelanggan yang membeli sebelum setup pertama tetap dapat menambahkan akun saat paid aktif; paid expired tidak dapat memakai pengecualian setup.

Trial 7 × 24 jam dimulai hanya setelah POST eksplisit; immutable per bisnis. Langganan Rp149.000 untuk 30 hari; approval memperpanjang dari max(waktu sekarang, akhir paid sebelumnya). Pending/rejected tidak mengaktifkan periode. Request nonce tetap mengarah ke tagihan sama bahkan jika replay setelah verified. Pembayaran langganan tidak masuk ledger pelanggan dan tidak mengubah Brain.

Login mempertahankan hanya product key allowlisted; ID bisnis selalu divalidasi. Setup bisnis memakai identitas request per user di bawah transaction lock; bisnis bernama sama tidak digabung. Akun pencatatan pertama dibuat hanya pada setup eksplisit. Checkout Brain GET kini halaman review tanpa pembuatan order; POST memakai engine existing dengan lock. Alur brief/fixed/custom/personal tetap menggunakan implementasi existing.

Default `internal_beta` mempertahankan kebijakan lama. `self_service` membuka workflow pelanggan berdasarkan membership + entitlement aktif; Analyst/Operator juga memerlukan capability flag. Emergency disable mengalahkan write/AI. Trial habis dihitung saat request tanpa cron: historical read/export tetap, paid AI/write/draft/share baru ditolak. Enforcement di dalam business write lock menangani expiry antara draft dan confirm. Billing renewal tetap tersedia saat expired/emergency.

Assistant, kamera, upload dan CSV memakai endpoint/validator lama. Struk tetap signed review; bank tetap REVIEW → OPEN eksplisit → keputusan manusia. Tidak ada raw statement/archive/chat history baru. Bukti pembayaran langganan gambar disimpan terbatas pada typed billing record, berbeda dari struk atau mutasi. Recurring preview read-only menampilkan maksimum 100 kejadian berikutnya, satu per rule; hanya pilihan yang dikonfirmasi diproses. Tunggakan berikutnya ditinjau lagi; tidak ada scheduler.

## Audit keamanan terbatas yang dilakukan

- Managed origins Operator, Invoice Payment, Recurring, Receipt, Bank dan perbaikan whitespace Phase 6C dipertahankan melalui full Finance regression.
- CSRF global, membership, Jinja escaping/textContent, no-store dan safe errors digunakan pada route baru. Public catalog tidak menampilkan private data.
- Subscription verification memeriksa role KILAS_ADMIN dan server-owned product/amount/currency/proof; audit dan period update dalam transaction yang sama.
- Nominal integer IDR; harga di konfigurasi server, bukan form browser. Semua trial/billing/staging/analyze tidak mengubah totals ledger.
- PDF subprocess/resource isolation dan batas Phase 6A/6B tidak dilonggarkan. CSV deterministik tidak memakai AI; confirmations tidak memakai AI; quota shared tetap berlaku.
- Concurrency dan rollback diuji di SQLite. PostgreSQL adapter/parity tidak disebut sebagai verifikasi PostgreSQL nyata.
- Secret scan statis memeriksa pola API/private key/credential URI dan file terlarang sebelum pengemasan. Contoh credential URI pada test/doc bukan secret nyata. Pemindaian bukan jaminan mendeteksi setiap secret yang mungkin ada.

## Batas dan keputusan yang perlu diketahui

Tidak ada payment gateway/auto debit/live bank sync. Admin wajib memverifikasi bukti transfer secara nyata. Trial sekali per bisnis tidak mencegah penyalahgunaan lewat identitas/bisnis baru. Quota AI/rate limiter process-local; deployment multiworker memerlukan kontrol tambahan di masa depan. Akurasi ekstraksi wajib dikoreksi manusia. Browser visual, PostgreSQL nyata dan provider nyata belum diverifikasi. Lihat HASIL_UJI.md serta checklist deployment sebelum membuka self-service.

## Perubahan ekspektasi tes lama

Tes checkout yang sebelumnya membuat order melalui GET kini melakukan POST setelah review; tes baru membuktikan GET tidak menulis dan POST idempotent. Tes recurring UI kini mengirim pilihan explicit. Teks bahasa awam mengganti jargon tanpa mengubah perhitungan. Tes 6C mengizinkan migration 0032 rilis ini dengan tetap mempertahankan 0031. Dua ekspektasi stale diperbaiki sesuai source yang sudah ada: label admin “Proyek perlu tindakan” dan katalog “Kilas Brain” tanpa penawaran Pro yang sudah pensiun. Tidak ada test case yang dihapus untuk menyembunyikan kegagalan. File historical test_ai_onboarding_features_enabled_fix.py memang kosong pada baseline; runner kini melaporkannya sebagai empty_modules=1, bukan sebagai tes lulus atau error aplikasi. Test file kosong tetap dipertahankan.
