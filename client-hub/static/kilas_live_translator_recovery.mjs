// Discover only the signed-in owner's session; never replace or end it on a read.
export class TranslatorRecovery {
  constructor({api, isIdle = () => true, onChange = () => {}, onError = () => {}}) {
    Object.assign(this, {api, isIdle, onChange, onError});
    this.active = null; this.checked = false; this.pending = false; this.ending = false; this.version = 0;
  }
  canStart() { return this.checked && !this.pending && !this.active; }
  changed() { this.onChange(this); }
  async refresh() {
    if (!this.isIdle() || this.pending) return false;
    const ticket = ++this.version;
    this.pending = true; this.changed();
    try {
      const result = await this.api.active();
      if (ticket !== this.version) return false;
      if (!result || !Object.hasOwn(result, 'session') || (result.session !== null && (!result.session || typeof result.session.session_id !== 'string' || !result.session.session_id))) {
        throw Error('Status sesi belum terverifikasi. Periksa sesi saat jaringan siap.');
      }
      this.active = result.session; this.checked = true;
      return !this.active;
    } catch (error) {
      if (ticket === this.version) {
        this.checked = false;
        this.onError(error.message || 'Status sesi belum dapat diperiksa. Periksa sesi saat jaringan siap.');
      }
      return false;
    } finally {
      if (ticket === this.version) { this.pending = false; this.changed(); }
    }
  }
  async endKnown(id) {
    if (!id || this.ending) return false;
    const ticket = ++this.version;
    this.ending = true; this.pending = true; this.checked = false;
    this.active = {session_id: id}; this.changed();
    let confirmed = false;
    try {
      await this.api.end(id); confirmed = true;
      if (ticket === this.version) this.active = null;
    } catch {
      if (ticket === this.version) {
        this.checked = true;
        this.onError('Sesi belum terkonfirmasi berakhir. Periksa sesi atau akhiri kembali saat jaringan siap.');
      }
    } finally {
      if (ticket === this.version) { this.ending = false; this.pending = false; this.changed(); }
    }
    // Another tab may have started in the meantime. Do not end that new session.
    if (confirmed) await this.refresh();
    return confirmed;
  }
  endPrevious() {
    return this.isIdle() && this.active && !this.pending ? this.endKnown(this.active.session_id) : Promise.resolve(false);
  }
}
