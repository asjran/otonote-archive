/** Binary heap: compare(a,b) < 0 means a must be visited first. */
export class SearchQueue {
  constructor(values = [], compare) { this.items = []; this.compare = compare; for (const value of values) this.push(value); }
  get length() { return this.items.length; }
  peek() { return this.items[0]; }
  snapshot() { return this.items.slice(); }
  clear() { this.items.length = 0; }
  push(value) {
    let i = this.items.length; this.items.push(value);
    while (i) { const p = (i - 1) >>> 1; if (this.compare(this.items[p], value) <= 0) break; this.items[i] = this.items[p]; i = p; }
    this.items[i] = value;
  }
  pop() {
    const first = this.items[0], last = this.items.pop();
    if (this.items.length) {
      let i = 0;
      while (i * 2 + 1 < this.items.length) {
        let child = i * 2 + 1;
        if (child + 1 < this.items.length && this.compare(this.items[child + 1], this.items[child]) < 0) child++;
        if (this.compare(last, this.items[child]) <= 0) break;
        this.items[i] = this.items[child]; i = child;
      }
      this.items[i] = last;
    }
    return first;
  }
}
