// Static releases fetch prebuilt fragments; independent releases render them
// from the same pinned snapshot as the surrounding document.
export function requestPageResource(url, options) {
  const render = globalThis[Symbol.for('ournotes.page-resource.v1')];
  return render ? render(url, options) : fetch(url, options);
}
