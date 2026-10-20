"""Reversible Expense picker presentation, independent of ledger/category state."""
import re

# Distinct Indonesian words audited against the displayed Personal and Business
# catalogs. Match complete words, never substrings (e.g. Gas in Vegas). Shared
# English words such as Air, Film, Gas, Internet, Laundry and Bonus are preserved.
# This deliberately does not infer language from category ID, position or origin.
INDONESIAN_WORDS = frozenset('''
acara administrasi akomodasi aktivitas akuntan alat anak asuransi bahan bakar baku
barang belanja biaya pembayaran insentif ketenagakerjaan cicilan utang denda
operasional donasi gaji tenaga kerja pemanas hadiah hiburan hipotek iuran
lingkungan kehilangan keluarga kerusakan kesehatan komisi konsumsi karyawan
kurir lainnya lain langganan layanan rumah liburan listrik makanan makan minuman
tim promosi medis obat ongkos produksi pajak properti pakaian parkir pinjaman
kendaraan pembelian khusus pembersihan penatu pendidikan penerbangan peralatan
kecil perawatan kulit perbaikan perizinan perjalanan dinas perlengkapan
kebersihan permainan konten diskon prosedur kosmetik renovasi restoran rias
wajah sewa sampah selisih kurs servis staf tangga stok persediaan telepon
tempat tinggal tol transportasi daring lokal pengiriman umum utilitas dokumen
tak terduga bpjs bbm notaris ponsel kabel satelit mainan buku majalah
kecantikan bensin tunai pengobatan luar upah
'''.split())


def hidden_from_expense_picker(row, *, parent_label=None):
    """Only classify the effective label; English v4 aliases stay selectable."""
    if row['direction'] != 'EXPENSE':
        return False
    # The old utility seed's Air is Indonesian Water; a standalone English
    # Air category, or Air under an English parent, remains untouched.
    if row.get('display_name', row['name']).strip().casefold() == 'air' and (parent_label or '').strip().casefold() == 'utilitas':
        return True
    words = set(re.findall(r"[^\W\d_]+", row.get('display_name', row['name']).casefold()))
    return bool(words & INDONESIAN_WORDS)


def selectable_children(rows):
    return [row for row in rows if not row.get('expense_picker_hidden', False)]
