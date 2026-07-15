using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

namespace WowRaidAnalyzer
{
    /// <summary>
    /// Zero-dependency Windows host: serves static files and persists scoreboard/data JSON.
    /// End users need no Python — drop analysis JSON into ./data and open the home page.
    /// </summary>
    class Program
    {
        static string Root;
        static string DataDir;
        static string ScoreboardDir;
        static HttpListener Listener;
        const int DefaultPort = 8765;

        static int Main(string[] args)
        {
            Root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            DataDir = Path.Combine(Root, "data");
            ScoreboardDir = Path.Combine(Root, "scoreboard");
            Directory.CreateDirectory(DataDir);
            Directory.CreateDirectory(ScoreboardDir);

            int port = DefaultPort;
            bool openBrowser = true;
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--port" && i + 1 < args.Length) int.TryParse(args[++i], out port);
                if (args[i] == "--no-open") openBrowser = false;
            }

            string prefix = "http://127.0.0.1:" + port + "/";
            Listener = new HttpListener();
            Listener.Prefixes.Add(prefix);
            try
            {
                Listener.Start();
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("无法启动本地服务（端口可能被占用）: " + ex.Message);
                Console.Error.WriteLine("可尝试: RaidAnalyzer.exe --port 8877");
                return 1;
            }

            Console.WriteLine("========================================");
            Console.WriteLine("  WoW 开荒复盘 · 本地宿主");
            Console.WriteLine("  " + prefix);
            Console.WriteLine("  数据目录: " + DataDir);
            Console.WriteLine("  计分板:   " + ScoreboardDir);
            Console.WriteLine("  关闭本窗口即停止服务");
            Console.WriteLine("========================================");

            if (openBrowser)
            {
                try { Process.Start(new ProcessStartInfo { FileName = prefix, UseShellExecute = true }); }
                catch { }
            }

            while (Listener.IsListening)
            {
                try
                {
                    var ctx = Listener.GetContext();
                    ThreadPool.QueueUserWorkItem(_ => Handle(ctx));
                }
                catch (HttpListenerException) { break; }
                catch (ObjectDisposedException) { break; }
            }
            return 0;
        }

        static void Handle(HttpListenerContext ctx)
        {
            try
            {
                var req = ctx.Request;
                var res = ctx.Response;
                string path = Uri.UnescapeDataString(req.Url.AbsolutePath);
                if (string.IsNullOrEmpty(path) || path == "/") path = "/index.html";

                if (path.StartsWith("/api/", StringComparison.OrdinalIgnoreCase))
                {
                    HandleApi(req, res, path);
                    return;
                }

                // Friendly routes
                if (path.Equals("/report", StringComparison.OrdinalIgnoreCase)) path = "/report.html";
                else if (path.Equals("/scoreboard", StringComparison.OrdinalIgnoreCase)) path = "/scoreboard.html";
                else if (path.Equals("/verdict", StringComparison.OrdinalIgnoreCase)) path = "/scoreboard.html";
                else if (path.Equals("/audit", StringComparison.OrdinalIgnoreCase)) path = "/crown-fight-audit.html";

                ServeFile(res, path);
            }
            catch (Exception ex)
            {
                try { WriteText(ctx.Response, 500, "text/plain; charset=utf-8", "Internal error: " + ex.Message); }
                catch { }
            }
        }

        static void HandleApi(HttpListenerRequest req, HttpListenerResponse res, string path)
        {
            // GET /api/health
            if (path.Equals("/api/health", StringComparison.OrdinalIgnoreCase))
            {
                WriteJson(res, 200, "{\"ok\":true}");
                return;
            }

            // GET /api/data-files  → labeled catalog for UI switching
            if (path.Equals("/api/data-files", StringComparison.OrdinalIgnoreCase) && req.HttpMethod == "GET")
            {
                var items = new List<string>();
                string rootWcl = Path.Combine(Root, "wcl_hardcore_api.json");
                if (File.Exists(rootWcl))
                {
                    var info = new FileInfo(rootWcl);
                    items.Add(string.Format(
                        "{{\"path\":{0},\"name\":{1},\"label\":{2},\"size\":{3},\"mtime\":{4}}}",
                        JsonString("wcl_hardcore_api.json"),
                        JsonString(info.Name),
                        JsonString("wcl_hardcore_api.json（兼容默认）"),
                        info.Length,
                        (long)(info.LastWriteTimeUtc - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds
                    ));
                }
                if (Directory.Exists(DataDir))
                {
                    foreach (var file in Directory.GetFiles(DataDir, "wcl_*.json"))
                    {
                        var info = new FileInfo(file);
                        string web = "data/" + info.Name;
                        items.Add(string.Format(
                            "{{\"path\":{0},\"name\":{1},\"label\":{2},\"size\":{3},\"mtime\":{4}}}",
                            JsonString(web),
                            JsonString(info.Name),
                            JsonString(info.Name),
                            info.Length,
                            (long)(info.LastWriteTimeUtc - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds
                        ));
                    }
                }
                // Prefer freshest first (simple string mtime numeric at end — sort client-side)
                WriteJson(res, 200, "{\"schemaVersion\":1,\"files\":[" + string.Join(",", items.ToArray()) + "]}");
                return;
            }

            // GET /api/data/list
            if (path.Equals("/api/data/list", StringComparison.OrdinalIgnoreCase) && req.HttpMethod == "GET")
            {
                var items = new List<string>();
                foreach (var file in Directory.GetFiles(DataDir, "*.json"))
                {
                    var info = new FileInfo(file);
                    items.Add(string.Format(
                        "{{\"path\":{0},\"name\":{1},\"label\":{2},\"size\":{3},\"mtime\":{4}}}",
                        JsonString("data/" + info.Name),
                        JsonString(info.Name),
                        JsonString(info.Name),
                        info.Length,
                        (long)(info.LastWriteTimeUtc - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds
                    ));
                }
                WriteJson(res, 200, "[" + string.Join(",", items.ToArray()) + "]");
                return;
            }

            // GET /api/data/{name}
            var dataMatch = Regex.Match(path, @"^/api/data/([^/]+)$", RegexOptions.IgnoreCase);
            if (dataMatch.Success && req.HttpMethod == "GET")
            {
                string name = SanitizeFileName(dataMatch.Groups[1].Value);
                if (!name.EndsWith(".json", StringComparison.OrdinalIgnoreCase)) name += ".json";
                string full = Path.Combine(DataDir, name);
                if (!File.Exists(full)) { WriteJson(res, 404, "{\"error\":\"not found\"}"); return; }
                WriteBytes(res, 200, "application/json; charset=utf-8", File.ReadAllBytes(full));
                return;
            }

            // Prefer auto file: GET /api/data/latest
            if (path.Equals("/api/data/latest", StringComparison.OrdinalIgnoreCase) && req.HttpMethod == "GET")
            {
                FileInfo latest = null;
                foreach (var file in Directory.GetFiles(DataDir, "*.json"))
                {
                    var info = new FileInfo(file);
                    if (latest == null || info.LastWriteTimeUtc > latest.LastWriteTimeUtc) latest = info;
                }
                // Also accept root wcl_hardcore_api.json next to exe for convenience
                string rootWcl = Path.Combine(Root, "wcl_hardcore_api.json");
                if (File.Exists(rootWcl))
                {
                    var info = new FileInfo(rootWcl);
                    if (latest == null || info.LastWriteTimeUtc > latest.LastWriteTimeUtc) latest = info;
                }
                if (latest == null) { WriteJson(res, 404, "{\"error\":\"no data json\"}"); return; }
                WriteBytes(res, 200, "application/json; charset=utf-8", File.ReadAllBytes(latest.FullName));
                return;
            }

            // GET /api/notebook|/api/scoreboard  → catalog of days (local diary store)
            if ((path.Equals("/api/scoreboard", StringComparison.OrdinalIgnoreCase) ||
                 path.Equals("/api/notebook", StringComparison.OrdinalIgnoreCase)) &&
                req.HttpMethod == "GET")
            {
                var days = new List<string>();
                foreach (var file in Directory.GetFiles(ScoreboardDir, "day-*.json"))
                {
                    string raw = File.ReadAllText(file, Encoding.UTF8);
                    days.Add(raw);
                }
                // Also support store.json multi-day
                string storePath = Path.Combine(ScoreboardDir, "store.json");
                if (File.Exists(storePath))
                {
                    WriteBytes(res, 200, "application/json; charset=utf-8", File.ReadAllBytes(storePath));
                    return;
                }
                WriteJson(res, 200, "{\"schemaVersion\":2,\"days\":[" + string.Join(",", days.ToArray()) + "]}");
                return;
            }

            // GET/PUT/POST/DELETE /api/notebook|scoreboard/{date}
            var sbMatch = Regex.Match(path, @"^/api/(?:scoreboard|notebook)/(\d{4}-\d{2}-\d{2})$", RegexOptions.IgnoreCase);
            if (sbMatch.Success)
            {
                string date = sbMatch.Groups[1].Value;
                string dayFile = Path.Combine(ScoreboardDir, "day-" + date + ".json");
                string storePath = Path.Combine(ScoreboardDir, "store.json");

                if (req.HttpMethod == "GET")
                {
                    if (File.Exists(dayFile))
                    {
                        WriteBytes(res, 200, "application/json; charset=utf-8", File.ReadAllBytes(dayFile));
                        return;
                    }
                    WriteJson(res, 404, "{\"error\":\"day not found\"}");
                    return;
                }

                if (req.HttpMethod == "PUT" || req.HttpMethod == "POST")
                {
                    string body = ReadBody(req);
                    File.WriteAllText(dayFile, body, new UTF8Encoding(false));
                    UpsertStore(storePath, date, body);
                    WriteJson(res, 200, "{\"ok\":true,\"path\":" + JsonString("scoreboard/day-" + date + ".json") + "}");
                    return;
                }

                if (req.HttpMethod == "DELETE")
                {
                    if (File.Exists(dayFile)) File.Delete(dayFile);
                    RemoveFromStore(storePath, date);
                    WriteJson(res, 200, "{\"ok\":true}");
                    return;
                }
            }

            // PUT/POST /api/notebook|/api/scoreboard|/api/*/store  full store replace
            if ((path.Equals("/api/scoreboard", StringComparison.OrdinalIgnoreCase) ||
                 path.Equals("/api/notebook", StringComparison.OrdinalIgnoreCase) ||
                 path.Equals("/api/scoreboard/store", StringComparison.OrdinalIgnoreCase) ||
                 path.Equals("/api/notebook/store", StringComparison.OrdinalIgnoreCase)) &&
                (req.HttpMethod == "PUT" || req.HttpMethod == "POST"))
            {
                string body = ReadBody(req);
                string storePath = Path.Combine(ScoreboardDir, "store.json");
                File.WriteAllText(storePath, body, new UTF8Encoding(false));
                WriteJson(res, 200, "{\"ok\":true,\"path\":\"scoreboard/store.json\"}");
                return;
            }

            WriteJson(res, 404, "{\"error\":\"unknown api\"}");
        }

        static void UpsertStore(string storePath, string date, string dayJson)
        {
            string store;
            if (File.Exists(storePath))
            {
                store = File.ReadAllText(storePath, Encoding.UTF8);
                // naive replace/insert of day object by date field
                var re = new Regex("\\{[^{}]*\"date\"\\s*:\\s*\"" + Regex.Escape(date) + "\"[\\s\\S]*?\\}(?=,|\\])", RegexOptions.Multiline);
                if (re.IsMatch(store))
                    store = re.Replace(store, dayJson, 1);
                else
                {
                    int idx = store.LastIndexOf(']');
                    if (idx > 0)
                    {
                        bool empty = store.Substring(0, idx).TrimEnd().EndsWith("[");
                        store = store.Substring(0, idx) + (empty ? dayJson : "," + dayJson) + store.Substring(idx);
                    }
                    else
                        store = "{\"schemaVersion\":2,\"days\":[" + dayJson + "]}";
                }
            }
            else
            {
                store = "{\"schemaVersion\":2,\"days\":[" + dayJson + "]}";
            }
            File.WriteAllText(storePath, store, new UTF8Encoding(false));
        }

        static void RemoveFromStore(string storePath, string date)
        {
            if (!File.Exists(storePath)) return;
            string store = File.ReadAllText(storePath, Encoding.UTF8);
            var re = new Regex(",?\\{[^{}]*\"date\"\\s*:\\s*\"" + Regex.Escape(date) + "\"[\\s\\S]*?\\}", RegexOptions.Multiline);
            store = re.Replace(store, "");
            store = store.Replace("[,", "[").Replace(",]", "]");
            File.WriteAllText(storePath, store, new UTF8Encoding(false));
        }

        static void ServeFile(HttpListenerResponse res, string urlPath)
        {
            string relative = urlPath.TrimStart('/').Replace('/', Path.DirectorySeparatorChar);
            if (relative.Contains("..")) { WriteText(res, 403, "text/plain", "forbidden"); return; }
            string full = Path.Combine(Root, relative);
            if (!File.Exists(full))
            {
                WriteText(res, 404, "text/plain; charset=utf-8", "Not found: " + urlPath);
                return;
            }
            string ext = Path.GetExtension(full).ToLowerInvariant();
            string ctype = "application/octet-stream";
            if (ext == ".html") ctype = "text/html; charset=utf-8";
            else if (ext == ".js") ctype = "application/javascript; charset=utf-8";
            else if (ext == ".css") ctype = "text/css; charset=utf-8";
            else if (ext == ".json") ctype = "application/json; charset=utf-8";
            else if (ext == ".png") ctype = "image/png";
            else if (ext == ".svg") ctype = "image/svg+xml";
            else if (ext == ".ico") ctype = "image/x-icon";
            WriteBytes(res, 200, ctype, File.ReadAllBytes(full));
        }

        static string ReadBody(HttpListenerRequest req)
        {
            using (var reader = new StreamReader(req.InputStream, req.ContentEncoding ?? Encoding.UTF8))
                return reader.ReadToEnd();
        }

        static string SanitizeFileName(string name)
        {
            name = Path.GetFileName(name);
            foreach (char c in Path.GetInvalidFileNameChars())
                name = name.Replace(c, '_');
            return name;
        }

        static string JsonString(string s)
        {
            if (s == null) return "null";
            var sb = new StringBuilder("\"");
            foreach (char c in s)
            {
                if (c == '\\') sb.Append("\\\\");
                else if (c == '"') sb.Append("\\\"");
                else if (c == '\n') sb.Append("\\n");
                else if (c == '\r') sb.Append("\\r");
                else if (c == '\t') sb.Append("\\t");
                else sb.Append(c);
            }
            sb.Append('"');
            return sb.ToString();
        }

        static void WriteJson(HttpListenerResponse res, int code, string json)
        {
            WriteText(res, code, "application/json; charset=utf-8", json);
        }

        static void WriteText(HttpListenerResponse res, int code, string ctype, string text)
        {
            WriteBytes(res, code, ctype, Encoding.UTF8.GetBytes(text ?? ""));
        }

        static void WriteBytes(HttpListenerResponse res, int code, string ctype, byte[] body)
        {
            res.StatusCode = code;
            res.ContentType = ctype;
            res.ContentEncoding = Encoding.UTF8;
            res.Headers.Add("Cache-Control", "no-store");
            res.ContentLength64 = body.LongLength;
            res.OutputStream.Write(body, 0, body.Length);
            res.OutputStream.Close();
        }
    }
}
