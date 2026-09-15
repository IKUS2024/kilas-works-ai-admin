# AI cost model

Tanggal tarif default: **2026-09-15**. Sumber primer: [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing). Tarif standard inference dalam USD per 1 juta token, bukan biaya Meta. Tidak ada kurs IDR buatan.

| Model exact ID | Input uncached | Output | Cache read | Cache write 5m | Cache write 1h |
|---|---:|---:|---:|---:|---:|
| claude-haiku-4-5-20251001 | 1 | 5 | 0.10 | 1.25 | 2 |
| claude-sonnet-4-6 | 3 | 15 | 0.30 | 3.75 | 6 |

Tarif berada di `client-hub/ai_usage.py`, satu modul untuk bot dan Hub. `AI_MODEL_PRICING_JSON` mengganti keseluruhan mapping, bukan fuzzy alias/model-family fallback. Model tak dikenal, usage tidak lengkap, tarif tidak valid => biaya unknown. `AI_PRICING_DATE` memberi tanggal snapshot konfigurasi tarif. Rate override harus numeric dan menyertakan input, output, read, write, write_1h untuk setiap model.

USD = (uncached input × input rate + output × output rate + cache read × read rate + (cache creation total − 1h creation) × 5m write rate + 1h creation × 1h write rate) / 1,000,000. Cache read/write tidak dihitung lagi sebagai uncached input. Porsi 1h memakai breakdown usage provider. Historical estimate disimpan saat call, tidak direpricing diam-diam ketika config berubah.

IDR hanya dihitung jika `AI_COST_USD_IDR` diisi operator dengan kurs positif yang sah; default unset => unknown. Unknown satu call membuat agregat biaya total bersangkutan unknown, bukan total parsial yang terlihat murah. Cost/reply = semua biaya Anthropic di scope bulan tersebut / respons teks valid customer/owner/simulation dalam scope tersebut, termasuk overhead setup pada pembilang. Bukan metrik delivery WhatsApp. Demo/setup/FAQ/writing/Assist/payment-review tercatat sebagai call dan biaya, tidak dianggap respons chat pelanggan. Call tanpa usage provider tidak dibuatkan angka nol.

Cache hit ratio = proporsi call dengan cache_read_input_tokens > 0, bukan persentase token. Haiku/Sonnet dihitung dari exact model string yang tercatat. Klasifikasi normal/vision/complex berasal jalur aplikasi, tanpa classifier AI. Tenant NULL berarti platform, bukan tenant lain.

## Sebelum/sesudah konteks

Sebelum: request menyertakan seluruh list recent history yang dimuat existing path, hingga 20 pesan lama plus pesan user baru pada fixture. Prompt stabil memakai cache dan dynamic facts sudah melalui retrieval.
Sesudah: prompt stabil, cache dan dynamic facts tetap; hanya request history dipadatkan menjadi 8 terbaru + maksimal 4 lama relevan, dedupe, kronologis. Data disimpan tetap lengkap. Tidak ada layanan summarization tambahan.

Fixture deterministik 20 pesan lama + 1 pertanyaan baru:

| Ukuran | Baseline | Release |
|---|---:|---:|
| Pesan dalam request | 21 | 9 |
| Karakter isi history | 8,240 | 3,179 |
| Karakter payload JSON request | 21,453 | 16,392 |
| Fakta lama format logo SVG dipertahankan | ya | ya |

Pengurangan history **61.4%**; payload **23.6%**. Proxy kasar chars/4: sekitar 5,363 → 4,098, bukan tokenisasi Anthropic yang diukur. Perubahan nominal input token produksi bergantung bahasa, cache dan tipe percakapan. Ini bukan janji penghematan 23.6% untuk setiap pesan atau total invoice provider. Percakapan pendek yang sudah <8 pesan hampir tidak berubah, sementara gambar dan konteks panjang dapat berbeda jauh.

Ilustrasi aritmetika (bukan metrik produksi): 4,098 input uncached + 200 output Haiku = USD0.005098/call; 2,000 call identik = USD10.196. Proxy baseline 5,363 input + 200 output = USD0.006363/call atau USD12.726 untuk 2,000 call. Asumsi contoh tanpa cache dan tanpa overhead setup/vision; jangan menggunakannya sebagai bill estimate tenant. Cache aktual harus dibaca dari ledger. Margin IDR tetap unknown tanpa kurs. Reference revenue 499000 hanya acuan paket, bukan pendapatan invoice aktual, terutama tenant legacy/historical discounts.

## Guardrails dan ENV

Semua opsional; tidak ada API key baru:

| ENV | Default | Kegunaan |
|---|---|---|
| KILAS_BRAIN_FAIR_USE_RESPONSES | 2000 | Soft monitor respons/business/bulan UTC |
| AI_COST_WARNING_USD | 10 | Warning estimasi biaya bulanan |
| AI_SONNET_WARNING_RATIO | 0.25 | Warning porsi Sonnet setelah >=10 calls |
| AI_NORMAL_INPUT_WARNING_TOKENS | 8000 | Warning rata-rata input normal termasuk cache |
| AI_COST_USD_IDR | unset | Konversi IDR; harus kurs sah positif |
| AI_MODEL_PRICING_JSON | built-in exact IDs di atas | Mapping tarif lengkap per model |
| AI_PRICING_DATE | 2026-09-15 | Tanggal tarif yang diterapkan |

WARNING fair use mulai 1500/default, HIGH mulai 2000/default. Tidak mematikan AI, tidak menjeda subscription, tidak otomatis menagih overage. Follow-up manual hanya. Client menerima copy fair-use sederhana, admin memperoleh metrics operasional.

## Keterbatasan

Ledger hanya usage Anthropic yang kembali; request gagal tanpa usage tidak dapat diestimasi. Semua biaya OpenAI voice transcription, provider lain, Meta, infrastruktur, pajak dan support di luar kalkulasi ini. Ledger fail-open dapat melewatkan satu record saat DB unavailable/lock timeout; safe failure log perlu dimonitor. Data mulai dari deploy + migrasi, tidak direkonstruksi dari isi chat lama. Koneksi pencatatan terpisah memiliki timeout terbatas dan tidak mengganggu transaksi aplikasi. Atur DATABASE_URL bersama agar bot dan Hub melihat ledger yang sama.
