"""Closed Phase 6 operational vocabulary; no model or delivery capability."""
REASONS = {
    'HUMAN_REPLY_NEEDED': 'Customer menunggu balasan tim',
    'READY_FOR_QUOTE': 'Siap ditinjau untuk penawaran',
    'NEEDS_INFORMATION_STUCK': 'Rincian perlu dibantu tim',
    'FOLLOWUP_DUE': 'Tindak lanjut perlu ditinjau',
    'REVIEW_REQUEST_DUE': 'Pekerjaan selesai, bisa diminta ulasan',
    'AUTOMATION_FAILED': 'Pesan otomatis belum tersimpan',
}
MESSAGES = {
    'CUSTOMER_INACTIVE_FOLLOWUP': 'Apakah masih ada yang ingin dilengkapi untuk kebutuhan Anda? Kami siap membantu di percakapan ini.',
    'JOB_COMPLETED_REVIEW_REQUEST': 'Terima kasih telah menggunakan layanan kami. Jika berkenan, boleh bagikan ulasan pengalaman Anda di sini?',
}
DEFAULT_CONFIG = {'followup_enabled': False, 'delay_hours': 24, 'max_attempts': 1, 'review_enabled': False}


class OperationError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


def config(payload):
    if type(payload) is not dict or set(payload) != set(DEFAULT_CONFIG):
        raise OperationError('invalid_config')
    for key in ('followup_enabled', 'review_enabled'):
        if type(payload[key]) is not bool:
            raise OperationError('invalid_config')
    for key, minimum, maximum in (('delay_hours', 1, 168), ('max_attempts', 1, 3)):
        if type(payload[key]) is not int or not minimum <= payload[key] <= maximum:
            raise OperationError('invalid_config')
    return dict(payload)
