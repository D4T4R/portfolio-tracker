import axios from "axios";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

// For hardcoded absolute URLs (localhost) or relative ones
axios.interceptors.request.use((config) => {
  if (typeof config.url === "string") {
    // If someone hardcoded localhost, rewrite it
    if (config.url.startsWith("http://localhost:5000")) {
      config.url = config.url.replace("http://localhost:5000", API_BASE);
    }
    // If it's a relative path, ensure base is applied
    if (!/^https?:\/\//.test(config.url)) {
      config.baseURL = API_BASE;
    }
  }
  return config;
});