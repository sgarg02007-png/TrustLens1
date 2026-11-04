// Local use: talks to the local server. When hosted online, it automatically uses the site's own address.
window.TRUSTLENS_API = (location.protocol === "file:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")
  ? "http://localhost:8000" : location.origin;
