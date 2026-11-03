/* Transport-only SSE fallback. The original application UI is unchanged. */
(() => {
  const Original = window.EventSource;
  class CaseEvents extends EventTarget {
    constructor(url, options) {
      super();
      const parsed = new URL(url, location.href);
      if (parsed.origin !== location.origin || !/^\/api\/v1\/cases\/[^/]+\/events$/.test(parsed.pathname)) {
        return new Original(url, options);
      }
      this.url = parsed.href;
      this.readyState = 1;
      this.withCredentials = true;
      this.closed = false;
      this.last = null;
      this.controller = new AbortController();
      this.casePath = parsed.pathname.replace(/\/events$/, '');
      this.timer = setTimeout(() => this.poll(), 250);
    }
    async poll() {
      if (this.closed) return;
      try {
        const response = await fetch(this.casePath, {credentials:'same-origin',cache:'no-store',signal:this.controller.signal});
        if (response.ok) {
          const snapshot = JSON.stringify(await response.json());
          if (snapshot !== this.last) {
            this.last = snapshot;
            this.dispatchEvent(new MessageEvent('changed', {data:'{}'}));
          }
        }
      } catch (error) {
        if (!this.closed) this.dispatchEvent(new Event('error'));
      }
      if (!this.closed) this.timer = setTimeout(() => this.poll(), 1500);
    }
    close() {
      this.closed = true;
      this.readyState = 2;
      this.controller.abort();
      clearTimeout(this.timer);
    }
  }
  Object.assign(CaseEvents,{CONNECTING:0,OPEN:1,CLOSED:2});
  window.EventSource = CaseEvents;
})();
