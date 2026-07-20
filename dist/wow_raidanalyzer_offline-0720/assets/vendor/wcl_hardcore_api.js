// Optional embedded-data hook. Offline build fills:
//   window.__WCL_DATA_BY_SOURCE__ = { "data/wcl_....json": {...}, ... }
//   window.__WCL_HARDCORE_DATA__ / __VERDICT_DATA__
// The offline loader falls back to fetch(source) (HTTP) or a local file picker (file://).
