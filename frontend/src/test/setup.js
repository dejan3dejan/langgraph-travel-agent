import '@testing-library/jest-dom'

// jsdom does not implement scrollIntoView, which App calls to keep the chat pinned to the latest
// message. Stub it so components that auto-scroll can be rendered under test.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}
